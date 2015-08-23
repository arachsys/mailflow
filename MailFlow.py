from AppKit import NSApplication, NSMenuItem
import objc
import re

def flow(text, width = 77):
    quote, indent = re.match(r'(>+ ?|)(\s*)', text, re.UNICODE).groups()
    prefix = len(quote)
    if text[prefix:] == u'-- ':
        return [text]
    text = text.rstrip(u' ')

    if not quote:
        if indent.startswith(u' ') or text.startswith(u'From '):
            text = u' ' + text
    if indent or len(text) <= width:
        return [text]

    matches = re.finditer(r'\S+\s*(?=\S|$)', text[prefix:], re.UNICODE)
    breaks, lines = [match.end() + prefix for match in matches], []
    while True:
        for index, cursor in enumerate(breaks[1:]):
            if len(text[:cursor].expandtabs()) >= width:
                cursor = breaks[index]
                break
        else:
            lines.append(text)
            return lines

        lines.append(text[:cursor] + u' ')
        if not quote and text[cursor:].startswith(u'From '):
            text, cursor = u' ' + text[cursor:], cursor - 1
        else:
            text, cursor = quote + text[cursor:], cursor - prefix
        breaks = [offset - cursor for offset in breaks[index + 1:]]

def swizzle(cls, selector):
    def decorator(function):
        old = cls.instanceMethodForSelector_(selector)
        if old.isClassMethod:
            old = cls.methodForSelector_(selector)
        def wrapper(self, *args, **kwargs):
            return function(self, old, *args, **kwargs)
        new = objc.selector(wrapper, selector = old.selector,
                            signature = old.signature,
                            isClassMethod = old.isClassMethod)
        objc.classAddMethod(cls, selector, new)
        return wrapper
    return decorator


class DocumentEditor(objc.Category(objc.runtime.DocumentEditor)):
    @swizzle(objc.runtime.DocumentEditor, 'finishLoadingEditor')
    def finishLoadingEditor(self, old):
        result = old(self)
        if self.messageType() in [1, 2, 3]:
            view = self.webView()
            document = view.mainFrame().DOMDocument()

            view.contentElement().removeStrayLinefeeds()
            blockquotes = document.getElementsByTagName_('BLOCKQUOTE')
            for index in xrange(blockquotes.length()):
                if blockquotes.item_(index):
                    blockquotes.item_(index).removeStrayLinefeeds()

            view.moveToBeginningOfDocument_(None)
            view.moveToEndOfParagraphAndModifySelection_(None)
            view.moveForwardAndModifySelection_(None)
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                'Decrease', 'changeQuoteLevel:', '')
            item.setTag_(-1)
            view.changeQuoteLevel_(item)

            attribution = view.selectedDOMRange().stringValue()
            if self.messageType() == 3:
                attribution = u'Forwarded message:\n'
            else:
                attribution = attribution.rsplit(u',', 1)[-1].lstrip()
            if view.isAutomaticTextReplacementEnabled():
                view.setAutomaticTextReplacementEnabled_(False)
                view.insertText_(attribution)
                view.setAutomaticTextReplacementEnabled_(True)
            else:
                view.insertText_(attribution)

            signature = document.getElementById_('AppleMailSignature')
            if signature:
                range = document.createRange()
                range.selectNode_(signature)
                view.setSelectedDOMRange_affinity_(range, 0)
                view.moveUp_(None)
            else:
                view.moveToEndOfDocument_(None)
                view.insertParagraphSeparator_(None)

            view.insertParagraphSeparator_(None)
            view.undoManager().removeAllActions()
            self.backEnd().setHasChanges_(False)
        return result


class MCMessageGenerator(objc.Category(objc.runtime.MCMessageGenerator)):
    @swizzle(objc.runtime.MCMessageGenerator, 'allows8BitMimeParts')
    def allows8BitMimeParts(self, old):
        return True

    @swizzle(objc.runtime.MCMessageGenerator,
             '_encodeDataForMimePart:withPartData:')
    def _encodeDataForMimePart_withPartData_(self, old, part, data):
        if part.type() != 'text' or part.subtype() != 'plain':
            return old(self, part, data)

        text = bytes(data.objectForKey_(part))
        if any(len(line) > 998 for line in text.splitlines()):
            return old(self, part, data)

        try:
            text.decode('ascii')
            part.setContentTransferEncoding_('7bit')
        except UnicodeDecodeError:
            part.setContentTransferEncoding_('8bit')
        return True

    @swizzle(objc.runtime.MCMessageGenerator,
             '_newPlainTextPartWithAttributedString:partData:')
    def _newPlainTextPartWithAttributedString_partData_(self, old, *args):
        result = old(self, *args)
        if not MailFlow.enabled.state():
            return result

        charset = result.bodyParameterForKey_('charset') or 'utf-8'
        data = args[1].objectForKey_(result)
        lines = bytes(data).decode(charset).splitlines()
        lines = [line for text in lines for line in flow(text)]
        data.setData_(buffer(u'\n'.join(lines).encode(charset)))

        result.setBodyParameter_forKey_('yes', 'delsp')
        result.setBodyParameter_forKey_('flowed', 'format')
        return result


class MessageViewController(objc.Category(objc.runtime.MessageViewController)):
    @swizzle(objc.runtime.MessageViewController, 'forward:')
    def forward_(self, old, *args):
        return self._messageViewer().forwardAsAttachment_(*args)


class MessageViewer(objc.Category(objc.runtime.MessageViewer)):
    @swizzle(objc.runtime.MessageViewer, 'forwardMessage:')
    def forwardMessage_(self, old, *args):
        return self.forwardAsAttachment_(*args)


class SingleMessageViewer(objc.Category(objc.runtime.SingleMessageViewer)):
    @swizzle(objc.runtime.SingleMessageViewer, 'forwardMessage:')
    def forwardMessage_(self, old, *args):
        return self.forwardAsAttachment_(*args)


class MailFlow(objc.runtime.MVMailBundle):
    @classmethod
    def initialize(self):
        application = NSApplication.sharedApplication()
        formatmenu = application.mainMenu().itemAtIndex_(6).submenu()
        self.enabled = formatmenu.addItemWithTitle_action_keyEquivalent_(
            'Flow Text', 'toggle:', '')
        self.enabled.setState_(True)
        self.enabled.setTarget_(self)
        self.registerBundle()

    @classmethod
    def toggle_(self, sender):
        self.enabled.setState_(1 - self.enabled.state())

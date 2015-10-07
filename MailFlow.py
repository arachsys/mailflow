from AppKit import NSAlternateKeyMask, NSApplication, NSMenuItem
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


class ComposeViewController(objc.Category(objc.runtime.ComposeViewController)):
    @swizzle(objc.runtime.ComposeViewController, 'finishLoadingEditor')
    def finishLoadingEditor(self, old):
        result = old(self)
        if self.messageType() not in [1, 2, 3]:
            return result

        view = self.composeWebView()
        document = view.mainFrame().DOMDocument()
        view.contentElement().removeStrayLinefeeds()
        blockquotes = document.getElementsByTagName_('BLOCKQUOTE')
        for index in xrange(blockquotes.length()):
            if blockquotes.item_(index):
                blockquotes.item_(index).removeStrayLinefeeds()

        if self.messageType() in [1, 2]:
            view.moveToBeginningOfDocument_(None)
            view.moveToEndOfParagraphAndModifySelection_(None)
            view.moveForwardAndModifySelection_(None)
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                'Decrease', 'changeQuoteLevel:', '')
            item.setTag_(-1)
            view.changeQuoteLevel_(item)

            attribution = view.selectedDOMRange().stringValue()
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

        if self.messageType() == 3:
            for index in xrange(blockquotes.length()):
                blockquote = blockquotes.item_(index)
                if blockquote.quoteLevel() == 1:
                    blockquote.parentNode().insertBefore__(
                        document.createElement_('BR'), blockquote)

        view.insertParagraphSeparator_(None)
        view.undoManager().removeAllActions()
        self.setHasUserMadeChanges_(False)
        self.backEnd().setHasChanges_(False)
        return result

    @swizzle(objc.runtime.ComposeViewController, 'show')
    def show(self, old):
        result = old(self)
        if self.messageType() in [1, 2]:
            view = self.composeWebView()
            document = view.mainFrame().DOMDocument()
            signature = document.getElementById_('AppleMailSignature')
            if signature:
                range = document.createRange()
                range.selectNode_(signature)
                view.setSelectedDOMRange_affinity_(range, 0)
                view.moveUp_(None)
            else:
                view.moveToEndOfDocument_(None)
        return result


class EditingMessageWebView(objc.Category(objc.runtime.EditingMessageWebView)):
    @swizzle(objc.runtime.EditingMessageWebView, 'decreaseIndentation:')
    def decreaseIndentation_(self, original, sender, indent = 2):
        if self.contentElement().className() != 'ApplePlainTextBody':
            return original(self, sender)

        self.undoManager().beginUndoGrouping()
        affinity = self.selectionAffinity()
        selection = self.selectedDOMRange()

        self.moveToBeginningOfParagraph_(None)
        if selection.collapsed():
            for _ in xrange(indent):
                self.moveForwardAndModifySelection_(None)
            text = self.selectedDOMRange().stringValue() or ''
            if re.match(u'[ \xa0]{%d}' % indent, text, re.UNICODE):
                self.deleteBackward_(None)
        else:
            while selection.compareBoundaryPoints__(1, # START_TO_END
                    self.selectedDOMRange()) > 0:
                for _ in xrange(indent):
                    self.moveForwardAndModifySelection_(None)
                text = self.selectedDOMRange().stringValue() or ''
                if re.match(u'[ \xa0]{%d}' % indent, text, re.UNICODE):
                    self.deleteBackward_(None)
                else:
                    self.moveBackward_(None)
                self.moveToEndOfParagraph_(None)
                self.moveForward_(None)

        self.setSelectedDOMRange_affinity_(selection, affinity)
        self.undoManager().endUndoGrouping()

    @swizzle(objc.runtime.EditingMessageWebView, 'increaseIndentation:')
    def increaseIndentation_(self, original, sender, indent = 2):
        if self.contentElement().className() != 'ApplePlainTextBody':
            return original(self, sender)

        self.undoManager().beginUndoGrouping()
        affinity = self.selectionAffinity()
        selection = self.selectedDOMRange()

        if selection.collapsed():
            position = self.selectedRange().location
            self.moveToBeginningOfParagraph_(None)
            position -= self.selectedRange().location
            self.insertText_(indent * u' ')
            for _ in xrange(position):
                self.moveForward_(None)
        else:
            self.moveToBeginningOfParagraph_(None)
            while selection.compareBoundaryPoints__(1, # START_TO_END
                    self.selectedDOMRange()) > 0:
                self.moveToEndOfParagraphAndModifySelection_(None)
                if not self.selectedDOMRange().collapsed():
                    self.moveToBeginningOfParagraph_(None)
                    self.insertText_(indent * u' ')
                    self.moveToEndOfParagraph_(None)
                self.moveForward_(None)
            self.setSelectedDOMRange_affinity_(selection, affinity)

        self.undoManager().endUndoGrouping()


class MCMessage(objc.Category(objc.runtime.MCMessage)):
    @swizzle(objc.runtime.MCMessage, 'forwardedMessagePrefixWithSpacer:')
    def forwardedMessagePrefixWithSpacer_(self, old, *args):
        return u''


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
        event = NSApplication.sharedApplication().currentEvent()
        result = old(self, *args)
        if event and event.modifierFlags() & NSAlternateKeyMask:
            return result

        charset = result.bodyParameterForKey_('charset') or 'utf-8'
        data = args[1].objectForKey_(result)
        lines = bytes(data).decode(charset).splitlines()
        lines = [line for text in lines for line in flow(text)]
        data.setData_(buffer(u'\n'.join(lines).encode(charset)))

        result.setBodyParameter_forKey_('yes', 'delsp')
        result.setBodyParameter_forKey_('flowed', 'format')
        return result


class MCMimePart(objc.Category(objc.runtime.MCMimePart)):
    @swizzle(objc.runtime.MCMimePart, 'decodeTextPlainWithContext:')
    def decodeTextPlainWithContext_(self, old, *args):
        result = old(self, *args)
        if result.startswith(u' '):
            result = u'&nbsp;' + result[1:]
        return result.replace(u'<BR> ', u'<BR>&nbsp;')


class MessageViewController(objc.Category(objc.runtime.MessageViewController)):
    @swizzle(objc.runtime.MessageViewController, 'forward:')
    def forward_(self, old, *args):
        event = NSApplication.sharedApplication().currentEvent()
        if event and event.modifierFlags() & NSAlternateKeyMask:
            return old(self, *args)
        return self._messageViewer().forwardAsAttachment_(*args)


class MessageViewer(objc.Category(objc.runtime.MessageViewer)):
    @swizzle(objc.runtime.MessageViewer, 'forwardMessage:')
    def forwardMessage_(self, old, *args):
        event = NSApplication.sharedApplication().currentEvent()
        if event and event.modifierFlags() & NSAlternateKeyMask:
            return old(self, *args)
        return self.forwardAsAttachment_(*args)


class SingleMessageViewer(objc.Category(objc.runtime.SingleMessageViewer)):
    @swizzle(objc.runtime.SingleMessageViewer, 'forwardMessage:')
    def forwardMessage_(self, old, *args):
        event = NSApplication.sharedApplication().currentEvent()
        if event and event.modifierFlags() & NSAlternateKeyMask:
            return old(self, *args)
        return self.forwardAsAttachment_(*args)


class MailFlow(objc.runtime.MVMailBundle):
    @classmethod
    def initialize(self):
        self.registerBundle()

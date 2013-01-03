"""This module is a set of functions, which load Parser from Kate XML files
"""

import copy
import sys
import xml.etree.ElementTree
import re

from qutepart.syntax.colortheme import ColorTheme
from qutepart.syntax.syntax import TextFormat


try:
    import qutepart.syntax.cParser as _parserModule
except ImportError:
    print >> sys.stderr, 'Failed to import quick parser in C. Using slow parser for syntax highlighting'
    import qutepart.syntax.parser as _parserModule


_seqReplacer = re.compile('\\\\.')

_escapeSequences = \
{  '\\': '\\',
  'a': '\a',
  'b': '\b',
  'f': '\f',
  'n': '\n',
  'r': '\r',
  't': '\t',}


def _processEscapeSequences(replaceText):
    """Replace symbols like \n \\, etc
    """
    def _replaceFunc(escapeMatchObject):
        char = escapeMatchObject.group(0)[1]
        if char in _escapeSequences:
            return _escapeSequences[char]
        
        return escapeMatchObject.group(0)  # no any replacements, return original value

    return _seqReplacer.sub(_replaceFunc, replaceText)


_DEFAULT_ATTRIBUTE_TO_STYLE_MAP = \
{
    'alert' : 'dsAlert',
    'base-n integer' : 'dsBaseN',
    'character' : 'dsChar',
    'string char': 'dsChar',
    'comment' : 'dsComment',
    'data type' : 'dsDataType',
    'decimal/value' : 'dsDecVal',
    'error' : 'dsError',
    'floating point' : 'dsFloat',
    'function' : 'dsFunction',
    'keyword' : 'dsKeyword',
    'normal' : 'dsNormal',
    'others' : 'dsOthers',
    'region marker' : 'dsRegionMarker',
    'string' : 'dsString'
}

_KNOWN_STYLES = set([  "dsNormal",
                       "dsKeyword",
                       "dsDataType",
                       "dsDecVal",
                       "dsBaseN",
                       "dsFloat",
                       "dsChar",
                       "dsString",
                       "dsComment",
                       "dsOthers",
                       "dsAlert",
                       "dsFunction",
                       "dsRegionMarker",
                       "dsError",
                       "CustomTmpForDebugging"])

_DEFAULT_DELIMINATOR = " \t.():!+,-<=>%&*/;?[]^{|}~\\"

def _parseBoolAttribute(value):
    if value.lower() in ('true', '1'):
        return True
    elif value.lower() in ('false', '0'):
        return False
    else:
        raise UserWarning("Invalid bool attribute value '%s'" % value)

def _safeGetRequiredAttribute(xmlElement, name, default):
    if name in xmlElement.attrib:
        return unicode(xmlElement.attrib[name])
    else:
        print >> sys.stderr, "Required attribute '%s' is not set for element '%s'" % (name, xmlElement.tag)
        return default

def _makeContextSwitcher(contextOperation, contexts):
    popsCount = 0
    contextToSwitch = None
    
    rest = contextOperation
    while rest.startswith('#pop'):
        popsCount += 1
        rest = rest[len('#pop'):]
    
    if rest == '#stay':
        if popsCount:
            print >> sys.stderr, "Invalid context operation '%s'" % contextOperation
    elif rest in contexts:
        contextToSwitch = contexts[rest]
    elif rest.startswith('##'):
        pass  # TODO implement IncludeRules
    elif rest:
        print >> sys.stderr, "Unknown context '%s'" % rest

    if popsCount > 0 or contextToSwitch != None:
        return _parserModule.ContextSwitcher(popsCount, contextToSwitch, contextOperation)
    else:
        return None
    

################################################################################
##                               Rules
################################################################################

def _loadIncludeRules(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    contextName = _safeGetRequiredAttribute(xmlElement, "context", None)
    
    if contextName is not None:
        if contextName in parentContext.parser.contexts:
            context = parentContext.parser.contexts[contextName]
        elif contextName.startswith('##'):
            syntaxName = contextName[2:]
            parser = parentContext.parser.syntax.manager.getSyntaxByName(syntaxName, formatConverterFunction).parser
            context = parser.defaultContext
        else:
            print >> sys.stderr, 'Invalid context name', contextName
            context = parentContext.parser.defaultContext
    else:
        context = parentContext.parser.defaultContext

    abstractRuleParams = _loadAbstractRuleParams(parentContext,
                                                 xmlElement,
                                                 attributeToFormatMap,
                                                 formatConverterFunction)
    return _parserModule.IncludeRules(abstractRuleParams, context)

def _simpleLoader(classObject):
    def _load(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
        abstractRuleParams = _loadAbstractRuleParams(parentContext,
                                                     xmlElement,
                                                     attributeToFormatMap,
                                                     formatConverterFunction)
        return classObject(abstractRuleParams)
    return _load

def _loadChildRules(context, xmlElement, attributeToFormatMap, formatConverterFunction):
    """Extract rules from Context or Rule xml element
    """
    rules = []
    for ruleElement in xmlElement.getchildren():
        if not ruleElement.tag in _ruleClassDict:
            raise ValueError("Not supported rule '%s'" % ruleElement.tag)
        rule = _ruleClassDict[ruleElement.tag](context, ruleElement, attributeToFormatMap, formatConverterFunction)
        rules.append(rule)
    return rules

def _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    # attribute
    attribute = xmlElement.attrib.get("attribute", None)
    if not attribute is None:
        attribute = attribute.lower()  # not case sensitive
        try:
            format = attributeToFormatMap[attribute]
            if formatConverterFunction is not None and format is not None:
                format = formatConverterFunction(format)
        except KeyError:
            print >> sys.stderr, 'Unknown rule attribute', attribute
            format = parentContext.format
    else:
        format = parentContext.format
    
    # context
    contextText = xmlElement.attrib.get("context", '#stay')
    context = _makeContextSwitcher(contextText, parentContext.parser.contexts)

    lookAhead = _parseBoolAttribute(xmlElement.attrib.get("lookAhead", "false"))
    firstNonSpace = _parseBoolAttribute(xmlElement.attrib.get("firstNonSpace", "false"))
    dynamic = _parseBoolAttribute(xmlElement.attrib.get("dynamic", "false"))
    
    # TODO beginRegion
    # TODO endRegion
    
    column = xmlElement.attrib.get("column", None)
    if column is not None:
        column = int(column)
    else:
        column = -1
    
    return _parserModule.AbstractRuleParams(parentContext, format, attribute, context, lookAhead, firstNonSpace, dynamic, column)

def _loadDetectChar(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    
    char = _safeGetRequiredAttribute(xmlElement, "char", None)
    if char is not None:
        char = _processEscapeSequences(char)
    
    index = 0
    if abstractRuleParams.dynamic:
        try:
            index = int(char)
        except ValueError:
            print >> sys.stderr, 'Invalid DetectChar char', char
            index = 0
        char = None
        if index <= 0:
            print >> sys.stderr, 'Too little DetectChar index', char
            index = 0

    return _parserModule.DetectChar(abstractRuleParams, unicode(char), index)

def _loadDetect2Chars(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    char = _safeGetRequiredAttribute(xmlElement, 'char', None)
    char1 = _safeGetRequiredAttribute(xmlElement, 'char1', None)
    if char is None or char1 is None:
        string = None
    else:
        string = _processEscapeSequences(char) + _processEscapeSequences(char1)
    
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    return _parserModule.Detect2Chars(abstractRuleParams, string)

def _loadAnyChar(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    string = _safeGetRequiredAttribute(xmlElement, 'String', '')
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    return _parserModule.AnyChar(abstractRuleParams, string)

def _loadStringDetect(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    string = _safeGetRequiredAttribute(xmlElement, 'String', None)
    
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    return _parserModule.StringDetect(abstractRuleParams,
                                      string)

def _loadWordDetect(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    word = _safeGetRequiredAttribute(xmlElement, "String", "")
    insensitive = _parseBoolAttribute(xmlElement.attrib.get("insensitive", "false"))
    
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    
    return _parserModule.WordDetect(abstractRuleParams, word, insensitive)

def _loadKeyword(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    string = _safeGetRequiredAttribute(xmlElement, 'String', None)
    try:
        words = parentContext.parser.lists[string]
    except KeyError:
        print >> sys.stderr, "List '%s' not found" % string
        
        words = list()
    
    insensitive = _parseBoolAttribute(xmlElement.attrib.get("insensitive", "false"))
    
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    return _parserModule.keyword(abstractRuleParams, words, insensitive)

def _loadRegExpr(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    def _processCraracterCodes(text):
        """QRegExp use \0ddd notation for character codes, where d in octal digit
        i.e. \0377 is character with code 255 in the unicode table
        Convert such notation to unicode text
        """
        text = unicode(text)
        def replFunc(matchObj):
            matchText = matchObj.group(0)
            charCode = eval(matchText[1:])
            return chr(charCode).decode('latin1')
        return re.sub(r"\\0\d\d\d", replFunc, text)

    insensitive = _parseBoolAttribute(xmlElement.attrib.get('insensitive', 'false'))
    string = _safeGetRequiredAttribute(xmlElement, 'String', None)        

    if string is not None:
        string = _processCraracterCodes(string)
        
        wordStart = string.strip('(').startswith('\\b')
        lineStart = string.strip('(').startswith('^')
    else:
        wordStart = False
        lineStart = False
    
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    return _parserModule.RegExpr(abstractRuleParams,
                                 string, insensitive, wordStart, lineStart)

def _loadAbstractNumberRule(rule, parentContext, xmlElement):
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    return _parserModule.NumberRule(abstractRuleParams, childRules)

def _loadInt(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    childRules = _loadChildRules(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    return _parserModule.Int(abstractRuleParams, childRules)

def _loadFloat(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    childRules = _loadChildRules(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    return _parserModule.Float(abstractRuleParams, childRules)

def _loadRangeDetect(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction):
    char = _safeGetRequiredAttribute(xmlElement, "char", 'char is not set')
    char1 = _safeGetRequiredAttribute(xmlElement, "char1", 'char1 is not set')
    
    abstractRuleParams = _loadAbstractRuleParams(parentContext, xmlElement, attributeToFormatMap, formatConverterFunction)
    return _parserModule.RangeDetect(abstractRuleParams, char, char1)


_ruleClassDict = \
{
    'DetectChar': _loadDetectChar,
    'Detect2Chars': _loadDetect2Chars,
    'AnyChar': _loadAnyChar,
    'StringDetect': _loadStringDetect,
    'WordDetect': _loadWordDetect,
    'RegExpr': _loadRegExpr,
    'keyword': _loadKeyword,
    'Int': _loadInt,
    'Float': _loadFloat,
    'HlCOct': _simpleLoader(_parserModule.HlCOct),
    'HlCHex': _simpleLoader(_parserModule.HlCHex),
    'HlCStringChar': _simpleLoader(_parserModule.HlCStringChar),
    'HlCChar': _simpleLoader(_parserModule.HlCChar),
    'RangeDetect': _loadRangeDetect,
    'LineContinue': _simpleLoader(_parserModule.LineContinue),
    'IncludeRules': _loadIncludeRules,
    'DetectSpaces': _simpleLoader(_parserModule.DetectSpaces),
    'DetectIdentifier': _simpleLoader(_parserModule.DetectIdentifier)
}

################################################################################
##                               Context
################################################################################


def _loadContexts(highlightingElement, parser, attributeToFormatMap, formatConverterFunction):
    contextsElement = highlightingElement.find('contexts')
    
    xmlElementList = contextsElement.findall('context')
    contextList = []
    for xmlElement in xmlElementList:
        name = _safeGetRequiredAttribute(xmlElement,
                                         u'name',
                                         u'Error: context name is not set!!!')
        context = _parserModule.Context(parser, name)
        contextList.append(context)

    defaultContext = contextList[0]
    
    contextDict = {}
    for context in contextList:
        contextDict[context.name] = context
    
    parser.setContexts(contextDict, defaultContext)
    
    # parse contexts stage 2: load contexts
    for xmlElement, context in zip(xmlElementList, contextList):
        _loadContext(context, xmlElement, attributeToFormatMap, formatConverterFunction)

def _loadContext(context, xmlElement, attributeToFormatMap, formatConverterFunction):
    """Construct context from XML element
    Contexts are at first constructed, and only then loaded, because when loading context,
    _makeContextSwitcher must have references to all defined contexts
    """
    attribute = _safeGetRequiredAttribute(xmlElement, 'attribute', '<not set>').lower()
    if attribute != '<not set>':  # there are no attributes for internal contexts, used by rules. See perl.xml
        try:
            format = attributeToFormatMap[attribute]
        except KeyError:
            print >> sys.stderr, 'Unknown context attribute', attribute
            format = TextFormat()
    else:
        format = None
    
    if formatConverterFunction is not None and format is not None:
        format = formatConverterFunction(format)
    
    lineEndContextText = xmlElement.attrib.get('lineEndContext', '#stay')
    lineEndContext = _makeContextSwitcher(lineEndContextText,  context.parser.contexts)
    lineBeginContextText = xmlElement.attrib.get('lineEndContext', '#stay')
    lineBeginContext = _makeContextSwitcher(lineBeginContextText, context.parser.contexts)
    
    if _parseBoolAttribute(xmlElement.attrib.get('fallthrough', 'false')):
        fallthroughContextText = _safeGetRequiredAttribute(xmlElement, 'fallthroughContext', '#stay')
        fallthroughContext = _makeContextSwitcher(fallthroughContextText, context.parser.contexts)
    else:
        fallthroughContext = None
    
    dynamic = _parseBoolAttribute(xmlElement.attrib.get('dynamic', 'false'))
    
    context.setValues(attribute, format, lineEndContext, lineBeginContext, fallthroughContext, dynamic)
    
    # load rules
    rules = _loadChildRules(context, xmlElement, attributeToFormatMap, formatConverterFunction)
    context.setRules(rules)

################################################################################
##                               Syntax
################################################################################

def _loadAttributeToFormatMap(highlightingElement):
    defaultTheme = ColorTheme(TextFormat)
    attributeToFormatMap = {}
    
    itemDatasElement = highlightingElement.find('itemDatas')
    for item in itemDatasElement.findall('itemData'):
        attribute, defaultStyleName = item.get('name'), item.get('defStyleNum')
        
        if not defaultStyleName in defaultTheme.format:
            print >> sys.stderr, "Unknown default style '%s'" % defaultStyleName
            defaultStyleName = 'dsNormal'
            
        format = copy.copy(defaultTheme.format[defaultStyleName])

        caseInsensitiveAttributes = {}
        for key, value in item.attrib.iteritems():
            caseInsensitiveAttributes[key.lower()] = value.lower()
        
        if 'color' in caseInsensitiveAttributes:
            format.color = caseInsensitiveAttributes['color']
        if 'selColor' in caseInsensitiveAttributes:
            format.selectionColor = caseInsensitiveAttributes['selColor']
        if 'italic' in caseInsensitiveAttributes:
            format.italic = _parseBoolAttribute(caseInsensitiveAttributes['italic'])
        if 'bold' in caseInsensitiveAttributes:
            format.bold = _parseBoolAttribute(caseInsensitiveAttributes['bold'])
        if 'underline' in caseInsensitiveAttributes:
            format.underline = _parseBoolAttribute(caseInsensitiveAttributes['underline'])
        if 'strikeout' in caseInsensitiveAttributes:
            format.strikeOut = _parseBoolAttribute(caseInsensitiveAttributes['strikeout'])
        if 'spellChecking' in caseInsensitiveAttributes:
            format.spellChecking = _parseBoolAttribute(caseInsensitiveAttributes['spellChecking'])
        
        attribute = attribute.lower()  # style names are not case sensitive
        attributeToFormatMap[attribute] = format
    
    return attributeToFormatMap
    
def _loadLists(root, highlightingElement):
    lists = {}  # list name: list
    for listElement in highlightingElement.findall('list'):
        # Sometimes item.text is none. Broken xml files
        items = [unicode(item.text.strip()) \
                    for item in listElement.findall('item') \
                        if item.text is not None]
        name = _safeGetRequiredAttribute(listElement, 'name', 'Error: list name is not set!!!')
        lists[name] = items
    
    return lists

def _makeKeywordsLowerCase(listDict):
    # Make all keywords lowercase, if syntax is not case sensitive
    for keywordList in listDict.values():
        for index, keyword in enumerate(keywordList):
            keywordList[index] = keyword.lower()

def _loadSyntaxDescription(root, syntax):
    syntax.name = _safeGetRequiredAttribute(root, 'name', 'Error: .parser name is not set!!!')
    syntax.section = _safeGetRequiredAttribute(root, 'section', 'Error: Section is not set!!!')
    syntax.extensions = _safeGetRequiredAttribute(root, 'extensions', '').split(';')
    syntax.mimetype = root.attrib.get('mimetype', '').split(';')
    syntax.version = root.attrib.get('version', None)
    syntax.kateversion = root.attrib.get('kateversion', None)
    syntax.priority = root.attrib.get('priority', None)
    syntax.author = root.attrib.get('author', None)
    syntax.license = root.attrib.get('license', None)
    syntax.hidden = _parseBoolAttribute(root.attrib.get('hidden', 'false'))

def loadSyntax(syntax, filePath, formatConverterFunction = None):
    with open(filePath, 'r') as definitionFile:
        root = xml.etree.ElementTree.parse(definitionFile).getroot()

    highlightingElement = root.find('highlighting')
    
    _loadSyntaxDescription(root, syntax)
    
    deliminatorSet = set(_DEFAULT_DELIMINATOR)
    
    # parse lists
    lists = _loadLists(root, highlightingElement)
    
    # parse itemData
    keywordsCaseSensitive = True

    generalElement = root.find('general')
    if generalElement is not None:
        keywordsElement = generalElement.find('keywords')
        
        if keywordsElement is not None:
            keywordsCaseSensitive = _parseBoolAttribute(keywordsElement.get('casesensitive', "true"))
            
            if not keywordsCaseSensitive:
                _makeKeywordsLowerCase(lists)

            if 'weakDeliminator' in keywordsElement.attrib:
                weakSet = keywordsElement.attrib['weakDeliminator']
                deliminatorSet.difference_update(weakSet)
            
            if 'additionalDeliminator' in keywordsElement.attrib:
                additionalSet = keywordsElement.attrib['additionalDeliminator']
                deliminatorSet.update(additionalSet)

    deliminatorSetAsString = u''.join(list(deliminatorSet))
    syntax._setParser(_parserModule.Parser(syntax, deliminatorSetAsString, lists, keywordsCaseSensitive))
    attributeToFormatMap = _loadAttributeToFormatMap(highlightingElement)
    
    # parse contexts
    _loadContexts(highlightingElement, syntax.parser, attributeToFormatMap, formatConverterFunction)

    return syntax
# -*- coding: utf-8 -*-

import audioinfo, os, pdb, sys, string, re
from decimal import Decimal, InvalidOperation
from pyparsing import (Word, alphas,Literal, OneOrMore, NotAny, alphanums, 
    nums, ZeroOrMore, Forward, delimitedList, Combine, QuotedString, 
    CharsNotIn, White, originalTextFor, nestedExpr, 
    Optional, commaSeparatedList)
from puddleobjects import PuddleConfig, safe_name
from funcprint import pprint
from puddlestuff.util import PluginFunction, translate, to_list, to_string
import cPickle as pickle
stringtags = audioinfo.stringtags
from copy import deepcopy
from constants import ACTIONDIR, CHECKBOX, SPINBOX, SYNTAX_ERROR, SYNTAX_ARG_ERROR
import glob
from collections import defaultdict
from functools import partial
numtimes = 0
import string

NOT_ALL = audioinfo.INFOTAGS + ['__image']
FILETAGS = audioinfo.FILETAGS
FUNC_NAME = 'func_name'
FIELDS = 'fields'
FUNC_MODULE = 'module'
ARGS = 'arguments'
KEYWORD_ARGS = set(['tags', 'm_tags', 'r_tags', 'state'])

whitespace = set(unicode(string.whitespace))

class ParseError(Exception):
    def __init__(self, message):
        Exception.__init__(self, message)
        self.message = message

class FuncError(ParseError): pass

class MultiValueError(FuncError): pass

from functions import functions, no_fields, pat_escape

def arglen_error(e, passed, function, to_raise = True):
    varnames = function.func_code.co_varnames[:function.func_code.co_argcount]
    args_len = len(passed)
    param_len = len(varnames)
    if args_len > param_len:
        message = translate('Functions',
            'At most %1 arguments expected. %2 given.')
    elif args_len < param_len:
        default_len = len(function.func_defaults) if \
            function.func_defaults else 0
        if args_len < (param_len - default_len):
            message = translate('Functions',
            'At least %1 arguments expected. %2 given.')
    else:
        raise e
    message = message.arg(unicode(param_len)).arg(unicode(args_len))
    if to_raise:
        raise ParseError(message)
    else:
        return message

def convert_actions(dirpath, new_dir):
    backup = os.path.join(dirpath, 'actions.bak')
    if not os.path.exists(backup):
        os.mkdir(backup)
    if not os.path.exists(new_dir):
        os.mkdir(new_dir)
    path_join = os.path.join
    basename = os.path.basename
    for filename in glob.glob(path_join(dirpath, '*.action')):
        funcs, name = get_old_action(filename)
        os.rename(filename, path_join(backup, basename(filename)))
        save_action(path_join(new_dir, basename(filename)), name, funcs)

def filenametotag(pattern, filename, checkext = False, split_dirs=True):
    """Retrieves tag values from your filename
        pattern is the rule with which to extract
        the tags from filename. Which does not have to
        be an existing file. Returns a dictionary with
        elements {tag:value} on success.
        If checkext=True, then the extension of the filename
        is included during the extraction process.

        E.g. if you want to retrieve a tags according to
        >>>pattern = "%artist% - %track% - %title%"
        You set a dictionary like so...
        >>>filename = "Mr. Jones - 123 - Title of a song"
        >>>filenametotag(pattern,filename)
        {"artist":"Mr. Jones", "track":"123","title":"Title of a song"}
        If checkext = True then filenametotag just operates on the
        filename and not the extension of the filename.

        E.g.
        >>>filename = "Mr. Jones - 123 - Title of a song.mp3"
        >>>filenametotag(pattern,filename)
        {"artist":"Mr. Jones", "track":"123","title":"Title of a song.mp3"}
        >>>filenametotag(pattern,filename, True)
        {"artist":"Mr. Jones", "track":"123","title":"Title of a song"}

        None is the returned if the pattern does not match the filename."""

    if checkext:
        filename = os.path.splitext(filename)[0]

    e = Combine(Literal("%").suppress() + OneOrMore(Word(alphas)) + Literal("%").suppress())
    patterns = filter(None, pattern.split(u'/'))
    if split_dirs:
        filenames = filename.split(u'/')[-len(patterns):]
    else:
        filenames = [filename]
    mydict = {}
    for pattern, filename in zip(patterns, filenames):
        new_fields = tagtotag(pattern, filename, e)
        if not new_fields:
            continue
        for key in new_fields:
            if key in mydict:
                mydict[key] += new_fields[key]
            else:
                mydict[key] = new_fields[key]
    if mydict:
        if mydict.has_key("dummy"):
            del(mydict["dummy"])
        return mydict
    return {}

def get_old_action(filename):
    """Gets the action from filename, where filename is either a string or
    file-like object.

    An action is just a list of functions with a name attached. In puddletag
    these are stored as pickled objects.

    Returns [list of Function objects, action name]."""
    if isinstance(filename, basestring):
        f = open(filename, "rb")
    else:
        f = filename
    name = pickle.load(f)
    funcs = pickle.load(f)
    f.close()
    return [funcs, name]

def load_action(filename):
    modules = defaultdict(lambda: defaultdict(lambda: {}))
    for function in functions.values():
        if isinstance(function, PluginFunction):
            f = function.function
            modules[f.__module__][f.__name__] = function
        else:
            modules[function.__module__][function.__name__] = function
    cparser = PuddleConfig(filename)
    funcs = []
    name = cparser.get('info', 'name', u'')
    for section in cparser.sections():
        if section.startswith(u'Func'):
            get = partial(cparser.get, section)
            func_name = get(FUNC_NAME, u'')
            fields = get(FIELDS, [])
            func_module = get(FUNC_MODULE, u'')
            arguments = get(ARGS, [])
            try:
                func = Function(modules[func_module][func_name], fields)
            except IndexError:
                continue
            except AttributeError:
                continue
            newargs = []
            for i, (control, arg) in enumerate(zip(func.controls, arguments)):
                if control == CHECKBOX:
                    if arg == u'False':
                        newargs.append(False)
                    else:
                        newargs.append(True)
                elif control == SPINBOX:
                    newargs.append(int(arg))
                else:
                    newargs.append(arg)
            if func.controls:
                func.args = newargs
            else:
                func.args = arguments
            funcs.append(func)
    return [funcs, name]

def load_action_from_name(name):
    filename = os.path.join(ACTIONDIR, safe_name(name) + '.action')
    return load_action(filename)

def func_tokens(dictionary, parse_action):
    func_name = Word(alphas+'_', alphanums+'_')

    func_ident = Combine('$' + func_name.copy()('funcname'))
    func_tok = func_ident + originalTextFor(nestedExpr())('args')
    func_tok.leaveWhitespace()
    func_tok.setParseAction(parse_action)
    func_tok.enablePackrat()

    rx_tok = Combine(Literal('$').suppress() + Word(nums)('num'))

    def replace_token(tokens):
        index = int(tokens.num)
        return dictionary.get(index, u'')

    rx_tok.setParseAction(replace_token)

    strip = lambda s, l, tok: tok[0].strip()
    text_tok = CharsNotIn(u',').setParseAction(strip)
    quote_tok = QuotedString('"')

    if dictionary:
        arglist = Optional(delimitedList(quote_tok | rx_tok | text_tok))
    else:
        arglist = Optional(delimitedList(quote_tok | text_tok))

    return func_tok, arglist, rx_tok

def get_function_arguments(func, arguments, reserved, fmt=True, *dicts):

    varnames = func.func_code.co_varnames[:func.func_code.co_argcount]

    #arguments will contain only a list of user supplied arguments
    #Eg. for the function $format(%artist%) the user will specify
    #only the %artist%, whereas calling the function requires
    #the tags in order to look it up.
    #This, and below replaces the tags with their corresponding order.
    
    topass = {}
    othervars = []

    key_args = set(KEYWORD_ARGS).union(reserved)
    
    for i, v in enumerate(varnames):
        if v in key_args:
            topass[v] = reserved[v]
        else:
            othervars.append(v)

    for no, (arg, param) in enumerate(zip(arguments, othervars)):
        if param.startswith('p_'):
            topass[param] = arg
        elif param.startswith('n_'):
            try:
                if float(arg) == int(float(arg)):
                    topass[param] = int(arg)
                else:
                    topass[param] = float(arg)
            except ValueError:
                raise ParseError(SYNTAX_ARG_ERROR % (funcname, no))
        else:
            if isinstance(arg, basestring) and fmt:
                topass[param] = replacevars(arg, *dicts)
            else:
                topass[param] = arg

    return topass

def run_format_func(funcname, arguments, m_audio, s_audio=None, extra=None,
    state=None):
    '''Runs the function function using the arguments specified from pudlestuff.function.

    Arguments:
    funcname  -- String with the function name. Looked up using the
                 dictionary pudlestuff.function.functions
    arguments -- List of arguments to pass to the function. Patterns
                 should not be evaluated. They'll be evaluated here.
    m_audio   -- Audio file containg multiple multiple values per key.
                 Eg. {'artist': [u'Artist1': 'Artist2']}

    Keyword Arguments
    s_audio -- Same as m_audio, but containing strings as values.
               Generated on each run unless also passed.
    extra -- Dictionary containing extra fields that are to be used
             when matching fields.
    state -- Dictionary that hold state. Like {'__count': 15}.
             Used by some functions in puddlestuff.functions
    
    '''
    
    #Get function
    try:
        if isinstance(funcname, basestring):
            func = functions[funcname]
        else:
            func = funcname
    except KeyError:
        raise ParseError(SYNTAX_ERROR % (func,
            translate('Defaults', 'function does not exist.')))

    extra = {} if extra is None else extra
    s_audio = stringtags(m_audio) if s_audio is None else s_audio
    
    reserved = {'tags': s_audio, 'm_tags': m_audio, 'state': state}
    dicts = [s_audio, extra, state]
    topass = get_function_arguments(func, arguments, reserved, True, *dicts)

    try:
        ret = func(**topass)
        if ret is None:
            return u''
        return ret
    except TypeError, e:
        message = SYNTAX_ERROR.arg(funcname)
        message = message.arg(arglen_error(e, topass, func, False))
        raise ParseError(message)
    except FuncError, e:
        message = SYNTAX_ERROR.arg(funcname).arg(e.message)
        raise ParseError(message)

def parsefunc(s, m_audio, s_audio=None, state=None, extra=None, ret_i=False):
    """Parses format strings. Returns the parsed string.

    Arguments
    ---------
    s  -- *Unicode* format string. Eg. $replace(%artist%, name, surname)
    m_audio -- Audio file containg multiple multiple values per key.
        Eg. {'artist': [u'Artist1': 'Artist2']}

    Keyword Arguments
    s_audio -- Same as m_audio, but containing strings as values.
        Generated on each run unless also passed.
    extra -- Dictionary containing extra fields that are to be used
             when matching fields.
    state -- Dictionary that hold state. Like {'__count': 15}.
             Used by some functions in puddlestuff.functions

    >>> audio = {'artist': [u'Artist1'], track:u'10'}
    >>> parsefunc(u'%track% - %artist%', m_audio)
    Artist1 - 10
    >>> state = {'__count': u'5'}
    >>> parsefunc(u'$num(%track%, 2)/$num(%__count%, 2). %artist%', m_audio,
    ... state = state)
    u'05/05. Artist1'

    """

    #Yes I know this is a big ass function...but it works and I can't
    #see a way to split it without making it complicated.
    
    tokens = []
    token = []
    #List containing a function with it's arguments
    #Will look like ['replace', arg1, arg2, arg3]
    #functions get evaluated as soon as closing bracket found.
    func = []
    #Flag determining if current within a function. Used for making comma's
    #significant
    in_func = False
    in_quote = False
    #field_open == -1 if not current in the middle of processing a field
    #eg. %artist%. Otherwise contains the index in s that the field started.
    field_open = -1
    #Determine if next char should be escaped.
    escape = False
        
    
    s_audio = stringtags(m_audio) if s_audio is None else s_audio
    state = {} if state is None else state
    tags = s_audio.copy()
    tags.update(state)
    tags.update(extra if extra is not None else {})

    br_error = translate('Errors', 'No closing bracket found.')

    i = 0
    while 1:
        try:
            c = s[i]
        except IndexError:  #  Parsing's done.
            if in_func:
                raise ParseError(SYNTAX_ERROR.arg(func[0]).arg(br_error))
            if token:
                tokens.append(replacevars(u''.join(token), tags))
            break

        if c == u'"' and not escape:
            if in_func:
                token.append(c)
            in_quote = not in_quote
        elif c == u'"' and escape and in_func:
            token.append(u'\\"')
            i += 1
            escape = False
            continue
        elif in_quote:
            token.append(c)
        elif c == u'\\' and not escape:
            escape = True
            i += 1
            continue
        elif c == u'$' and not (escape or (field_open >= 0)):
            func_name = re.search(u'^\$(\w+)\(', s[i:])
            if not func_name:
                token.append(c)
                i += 1
                continue

            if in_func:
                func_parsed, offset = parsefunc(s[i:], m_audio, s_audio, state, extra, True)
                token.append(func_parsed)
                i += offset + 1
                continue

            tokens.append(replacevars(u''.join(token), tags))
            token = []
            func = []
            func_name = func_name.groups(0)[0]
            func.append(func_name)
            in_func = True
            i += len(func_name) + 1
        elif in_func and not in_quote and not token and c in whitespace:
            'just increment counter'
        elif c == u',' and in_func and not in_quote:
            func.append(u''.join(token))
            token = []
        elif c == u')' and in_func:
            in_func = False
            if token or s[i-1] == u',':
                func.append(u''.join(token))
            func_parsed = run_format_func(func[0], func[1:], m_audio, s_audio)
            if ret_i:
                return func_parsed, i
            tokens.append(func_parsed)
            token = []
        else:
            token.append(c)
        escape = False
        i += 1


    return u''.join(tokens)

def parse_field_list(fields, audio, selected=None):
    fields = fields[::]
    not_fields = [i for i, z in enumerate(fields) if z.startswith('~')]

    if not_fields:
        index = not_fields[0]
        not_fields = fields[index:]
        not_fields[0] = not_fields[0][1:]
        while '__all' in not_fields:
            not_fields.remove('__all')

        if '__selected' in not_fields:
            if selected:
                not_fields.extend(selected)
            while '__selected' in not_fields:
                not_fields.remove('__selected')
        fields = fields[:index]
        fields.extend([key for key in audio if key not in
            not_fields and key not in NOT_ALL])

    if '__all' in fields:
        while '__all' in fields:
            fields.remove('__all')
        fields.extend([key for key in audio if key not in NOT_ALL])

    if '__selected' in fields:
        while '__selected' in fields:
            fields.remove('__selected')
        if selected:
            fields.extend(selected)
    return list(set(fields))

# This function is from name2id3 by  Kristian Kvilekval
def re_escape(rex):
    """Escape regular expression special characters"""
    escaped = ""
    for ch in rex:
        if ch in r'^$[]\+*?.(){},|' : escaped = escaped + '\\' + ch
        else: escaped = escaped + ch
    return escaped

def removeSpaces(text):
    for char in string.whitespace:
        text = text.replace(char, '')
    return text.lower()

def replacevars(pattern, *dicts):
    """Replaces occurrences of %key% with the d[key] in the string pattern.

    Arguments
    ---------
    pattern -- Format string like '%artist% - %title%'
    d -- Dictionary with string values.

    Optional Arguments
    ------------------
    *extra - Extra dictionaries to check. If a key can't be found in
            d, the other dictionaries will be checked in order.

    Returns the parsed string. If a key isn't found, but in the format
    string, it'll be removed.

    >>> replacevars('%artist%', {'artist': u'ARTIST'})
    u'ARTIST'
    >>> replacevars('one %two%', {"three": u'VALUE'})
    u'one '

    """
    r_vars = {}
    map(r_vars.update, [z for z in dicts if z])
    
    in_quote = False
    in_field = False
    ret = []
    field_start = 0
    escape = False

    for i, c in enumerate(pattern):
        if not in_quote and c == u'\\' and not escape:
            escape = True
            continue
        elif escape:
            if c == u'\\':
                ret.append(c)
            escape = False
        elif c == u'"':
            in_quote = not in_quote
            continue
        elif c == u'%' and not in_quote:

            if not in_field:
                field_start = len(ret)
                in_field = True
            elif in_field:
                in_field = False
                field = u''.join(ret[field_start:])
                del(ret[field_start:])
                ret.append(r_vars.get(field, u''))
            continue
        ret.append(c)

    return u''.join(ret)


def runAction(funcs, audio, state = None, quick_action=None):
    """Runs an action on audio

    funcs can be a list of Function objects or a filename of an action file (see load_action).
    audio must dictionary-like object."""
    if isinstance(funcs, basestring):
        funcs = load_action(funcs)[0]
    
    if state is None:
        state = {}
    if '__counter' not in state:
        state['__counter'] = 0
    state['__counter'] = unicode(int(state['__counter']) + 1)

    r_tags = audio
   
    if hasattr(audio, 'tags'):
        audio = deepcopy(audio.tags)
    else:
        audio = deepcopy(audio)

    changed = set()
    for func in funcs:
        if quick_action is None:
            fields = parse_field_list(func.tag, audio)
        else:
            fields = quick_action[::]
        ret = {}

        for field in fields:
            val = audio.get(field, u'')
            temp = func.runFunction(val, audio, state, None, r_tags)
            if temp is None:
                continue
            if isinstance(temp, basestring):
                ret[field] = temp
            elif hasattr(temp, 'items'):
                ret.update(temp)
                break
            elif not temp:
                continue
            elif hasattr(temp[0], 'items'):
                [ret.update(z) for z in temp]
                break
            elif isinstance(temp[0], basestring):
                if field in FILETAGS:
                    ret[field] = temp[0]
                else:
                    ret[field] = temp
            else:
                ret[field] = temp[0]
        ret = dict([z for z in ret.items() if z[1] is not None])
        if ret:
            [changed.add(z) for z in ret]
            audio.update(ret)
    return dict([(z, audio[z]) for z in changed])

def runQuickAction(funcs, audio, state, tag):
    """Same as runAction, except that all funcs are 
    applied not in the values stored but on audio[tag]."""
    return runAction(funcs, audio, state, tag)

def save_action(filename, name, funcs):
    f = open(filename, 'w')
    f.close()
    cparser = PuddleConfig(filename)
    cparser.set('info', 'name', name)
    set_value = lambda i, key, value: cparser.set('Func%d' % i, key, value)
    for i, func in enumerate(funcs):
        set_value(i, FIELDS, func.tag)
        set_value(i, FUNC_NAME, func.function.__name__)
        set_value(i, FUNC_MODULE, func.function.__module__)
        set_value(i, ARGS, func.args)

def saveAction(filename, actionname, funcs):
    """Saves an action to filename.

    funcs is a list of funcs, and actionname is...er...the name of the action."""
    if isinstance(filename, basestring):
        fileobj = open(filename, 'wb')
    else:
        fileobj = filename
    pickle.dump(actionname, fileobj)
    pickle.dump(funcs, fileobj)

def tagtofilename(pattern, filename, addext=False, extension=None, state=None):
    """
    tagtofilename sets the filename of an mp3 or ogg file
    according to the rule specified in pattern.

    E.g. if you have a mp3 file with
    tags = {"artist": "Amy Winehouse",
            "title": "Shitty Song",
            "track": "12"}
    and you want to create a filename like,
    >>>filename = "Amy Winehouse - 12 - Shitty Song" # you'd use
    >>>pattern = "%artist% - %track% - %title%"
    >>>tagtofilename(pattern,filename)
    Amy Winehouse - 12 - Shitty Song

    You can also have filename be the path to an music file.
    The tag of that file will then be used.

    If addext == True, then the extension of the file
    is added to the returned filename.

    You can use extension to set the extension of the file
    if the files extension does not match its contents.
    This is useful if you pass tagtofilename a dictionary, but
    want to add a '.mp3' extension.

    For instance, using pattern and filename as before:
    >>>tagtofilename(pattern, filename, True, ".mp3")
    Amy Winehouse - 12 - Shitty Song.mp3

    Note that addext has to be True if you want to set your own extension.

    tagtofilename returns None if tags are missing in filename, but
    used in pattern or if unsuccessful in any way.

    Lastly, function may also be in setting the filename. These
    functions are defined in functions.py and may be called by using
    a $functionname.

    E.g
    >>>pattern = '%artist% - %num(%track%,3) - %title%' #see functions.py for more on num.
    >>>tagtofilename(pattern, filename, True, '.mp3')
    Amy Winehouse - 012 - Shitty Song.mp3"""

    #First check if a filename was passed or a dictionary.
    if not isinstance(filename, basestring):
        #if it was a dictionary, then use that as the tags.
        tags = filename
    else:
        tags = audioinfo.Tag(filename)
        if not tags:
            return 0

    if not addext:
        return parsefunc(pattern, tags, state=state)
    elif addext and (extension is not None):
        return parsefunc(pattern, tags, state=state) + os.path.extsep + extension
    else:
        return parsefunc(pattern, tags, state=state) + os.path.extsep + tags["__ext"]

def tagtotag(pattern, text, expression):
    """See filenametotag for an implementation example and explanation.

    pattern is a string with position of each token in text
    text is the text to be matched
    expression is a pyparsing object (i.e. what a token look like)

    >>>tagtotag('$1 - $2', 'Artist - Title', Literal('$').suppress() + Word(nums))
    {'1': 'Artist', '2': 'Title'}
    """
    pattern = re_escape(pattern)
    taglist = []
    def what(s, loc, tok):
        global numtimes
        taglist.append(tok[0])
        numtimes -= 1
        if numtimes == 0:
            return "(.*)"
        return "(.*?)"
    expression.setParseAction(what)
    global numtimes
    numtimes = len([z for z in expression.scanString(pattern)])
    if not numtimes:
        return
    pattern = expression.transformString(pattern)
    try:
        tags = re.search(pattern, text).groups()
    except AttributeError:
        #No matches were found
        return  u''
    mydict={}
    for i in range(len(tags)):
        if mydict.has_key(taglist[i]):
            mydict[taglist[i]] = ''.join([mydict[taglist[i]],tags[i]])
        else:
            mydict[taglist[i]]=tags[i]
    return mydict

class Function:
    """Basically, a wrapper for functions, but makes it easier to
    call according to the needs of puddletag.
    Methods of importance are:

    description -> Returns the parsed description of the function.
    setArgs -> Sets the 2nd to last arguments that the function is to be called with.
    runFunction(arg1) -> Run the function with arg1 as the first argument.
    setTag -> Sets the tag of the function for editing of tags.

    self.info is a tuple with the first element is the function name form the docstring.
    The second element is the description in unparsed format.

    See the functions module for more info."""

    def __init__(self, funcname, fields=None):
        if isinstance(funcname, basestring):
            self.function = functions[funcname]
        elif isinstance(funcname, PluginFunction):
            self.function = funcname.function
            self.doc = [u','.join([funcname.name, funcname.print_string])] + \
                [','.join(z) for z in funcname.args]
            self.info = [funcname.name, funcname.print_string]
        else:
            self.function = funcname

        self.reInit()

        self.funcname = self.info[0]
        if fields is not None:
            self.tag = fields
        else:
            self.tag = ''
        self.args = None
        
        self.controls = self._getControls()

    def reInit(self):
        #Since this class gets pickled in ActionWindow, the class is never 'destroyed'
        #Since, a functions docstring wouldn't be reflected back to puddletag
        #if it were changed calling this function to 're-read' it is a good idea.
        if not self.function.__doc__:
            return
        self.doc = self.function.__doc__.split("\n")

        identifier = QuotedString('"') | Combine(Word(alphanums + ' !"#$%&\'()*+-./:;<=>?@[\\]^_`{|}~'))
        tags = delimitedList(identifier)

        self.info = [z for z in tags.parseString(self.doc[0])]

    def setArgs(self, args):
        self.args = args

    def runFunction (self, text=None, m_tags=None, state=None,
        tags=None, r_tags=None):

        func = self.function

        varnames = func.func_code.co_varnames[:func.func_code.co_argcount]

        if not varnames:
            return func()
            
        s_audio = stringtags(m_tags) if tags is None else tags
        m_audio = m_tags
        state = {} if state is None else state

        m_text = to_list(text)
        text = to_string(text)

        reserved = {'tags': s_audio, 'm_tags': m_audio, 'state': state,
            'r_tags': r_tags, 'text': to_string(text),
            'm_text': m_text}

        
        if varnames[0] in reserved:
            reserved = {'tags': s_audio, 'm_tags': m_audio, 'state': state,
                'r_tags': r_tags, 'text': to_string(text),
                'm_text': m_text}
            topass = get_function_arguments(func, self.args, reserved,
                False, *[s_audio, state])
            return func(**topass)
        else:
            reserved = {'tags': s_audio, 'm_tags': m_audio, 'state': state,
                'r_tags': r_tags}
            topass = get_function_arguments(func,
                [text] + self.args, reserved, False, *[s_audio, state])
            
        try:
            first_arg = [z for z in varnames if z not in reserved][0]
        except IndexError:
            return

        if not first_arg.startswith('m_'):
            text = m_text
            ret = []
            for z in text:
                topass[first_arg] = z
                ret.append(func(**topass))

            temp = []
            append = temp.append
            [append(z) for z in ret if z not in temp]
            return temp
        else:
            topass[first_arg]
            return func(**topass)

    def description(self):
        d = [u", ".join(self.tag)] + self.args
        return pprint(translate('Functions', self.info[1]), d)
        
    def _getControls(self, index=1):
        identifier = QuotedString('"') | CharsNotIn(',')
        arglist = delimitedList(identifier)
        docstr = self.doc[1:]
        if index:
            return [(arglist.parseString(line)[index]).strip()
                for line in docstr]
        else:
            ret = []
            for line in docstr:
                ret.append([z.strip() for z in arglist.parseString(line)])
            return ret

    def setTag(self, tag):
        self.tag = tag
        self.fields = tag

    def addArg(self, arg):
        if self.function.func_code.co_argcount > len(self.args) + 1:
            self.args.append(arg)


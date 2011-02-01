# -*- coding: utf-8 -*-
#actiondlg.py

#Copyright (C) 2008-2009 concentricpuddle

#This file is part of puddletag, a semi-good music tag editor.

#This program is free software; you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation; either version 2 of the License, or
#(at your option) any later version.

#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.

#You should have received a copy of the GNU General Public License
#along with this program; if not, write to the Free Software
#Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

from PyQt4.QtGui import *
from PyQt4.QtCore import *
from PyQt4 import QtGui, QtCore
import sys, findfunc, pdb, os, resource, string, functions
from copy import copy
from pyparsing import delimitedList, alphanums, Combine, Word, ZeroOrMore, \
        QuotedString, Literal, NotAny, nums
import cPickle as pickle
from puddleobjects import (ListBox, OKCancel, ListButtons, PuddleConfig,
    winsettings, gettaglist, settaglist, safe_name, ShortcutEditor)
from findfunc import Function, runAction, runQuickAction
from puddleobjects import PuddleConfig, PuddleCombo
from audioinfo import REVTAGS, INFOTAGS, READONLY, usertags, isempty
from functools import partial
from constants import (TEXT, COMBO, CHECKBOX, SEPARATOR, 
    SAVEDIR, ACTIONDIR, BLANK)
from util import open_resourcefile, PluginFunction, escape_html, translate
import functions_dialogs
from puddlestuff.puddleobjects import ShortcutEditor
from puddletag import status

READONLY = list(READONLY)
FUNC_SETTINGS = os.path.join(SAVEDIR, 'function_settings')

def to_str(v):
    if isempty(v):
        return escape_html(BLANK)
    elif isinstance(v, unicode):
        return escape_html(v)
    elif isinstance(v, str):
        return escape_html(v.decode('utf8', 'replace'))
    else:
        return escape_html(SEPARATOR.join(v))

def displaytags(tags):
    if tags:
        if isinstance(tags, basestring):
            return tags
        elif not hasattr(tags, 'items'):
            return SEPARATOR.join(filter(lambda x: x is not None, tags))
        s = u"<b>%s</b>: %s<br />"
        ret = u"".join([s % (z, to_str(v)) for z, v in sorted(tags.items()) 
            if z not in READONLY and z != '__image'])[:-2]
        if u'__image' in tags:
            ret += u'<b>__image</b>: %s images<br />' % len(tags['__image'])
        return ret
    else:
        return translate('Functions Dialog', '<b>No change.</b>')

class ShortcutDialog(QDialog):
    def __init__(self, shortcuts=None, parent=None):
        super(ShortcutDialog, self).__init__(parent)
        self.setWindowTitle('puddletag')
        self.ok = False
        label = QLabel(translate('Shortcut Editor', 'Enter a key sequence for the shortcut.'))
        self._text = ShortcutEditor(shortcuts)

        okcancel = OKCancel()
        okcancel.cancel.setText(translate('Shortcut Editor', "&Don't assign keyboard shortcut."))
        okcancel.ok.setEnabled(False)
        
        self.connect(okcancel, SIGNAL('ok'), self.okClicked)
        self.connect(okcancel, SIGNAL('cancel'), self.close)

        self.connect(self._text, SIGNAL('validityChanged'),
            okcancel.ok.setEnabled)

        vbox = QVBoxLayout()
        vbox.addWidget(label)
        vbox.addWidget(self._text)
        vbox.addLayout(okcancel)
        vbox.addStretch()
        self.setLayout(vbox)

        self._shortcuts = shortcuts

    def okClicked(self):
        self.emit(SIGNAL('shortcutChanged'), unicode(self._text.text()))
        self.ok = True
        self.close()

    def getShortcut(self):
        self.exec_()
        if self._text.valid:
            return unicode(self._text.text()), self.ok
        else:
            return u'', self.ok

class ShortcutName(QDialog):
    def __init__(self, texts, default=u'', parent=None):
        super(ShortcutName, self).__init__(parent)
        self.setWindowTitle('puddletag')
        self.ok = False
        self._texts = texts
        label = QLabel(translate('Actions', 'Enter a name for the shortcut.'))
        self._text = QLineEdit(default)

        okcancel = OKCancel()
        self._ok = okcancel.ok
        self.enableOK(self._text.text())

        self.connect(okcancel, SIGNAL('ok'), self.okClicked)
        self.connect(okcancel, SIGNAL('cancel'), self.close)

        self.connect(self._text, SIGNAL('textChanged(const QString)'),
            self.enableOK)

        vbox = QVBoxLayout()
        vbox.addWidget(label)
        vbox.addWidget(self._text)
        vbox.addLayout(okcancel)
        vbox.addStretch()
        self.setLayout(vbox)

    def okClicked(self):
        self.ok = True
        self.close()

    def enableOK(self, text):
        if text and unicode(text) not in self._texts:
            self._ok.setEnabled(True)
        else:
            self._ok.setEnabled(False)

    def getText(self):
        self.exec_()
        return unicode(self._text.text()), self.ok

class ScrollLabel(QScrollArea):
    def __init__(self, text = '', parent=None):
        QScrollArea.__init__(self, parent)
        label = QLabel()
        label.setMargin(3)
        self.setWidget(label)
        self.setText(text)
        self.text = label.text
        label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.setFrameStyle(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def wheelEvent(self, e):
        h = self.horizontalScrollBar()
        if h.isVisible():
            numsteps = e.delta() / 5
            h.setValue(h.value() - numsteps)
            e.accept()
        else:
            QScrollArea.wheelEvent(self, e)
    
    def setText(self, text):
        label = self.widget()
        label.setText(text)
        height = label.sizeHint().height()
        self.setMaximumHeight(height)
        self.setMinimumHeight(height)
        
class FunctionDialog(QWidget):
    "A dialog that allows you to edit or create a Function class."

    _controls = {'text': PuddleCombo, 'combo': QComboBox, 'check': QCheckBox}
    
    signals = {
        TEXT: SIGNAL('editTextChanged(const QString&)'),
        COMBO : SIGNAL('currentIndexChanged(int)'),
        CHECKBOX : SIGNAL('stateChanged(int)'),
        }

    def __init__(self, funcname, showcombo = False, userargs = None, 
        default_fields = None, parent = None, example = None, text = None):
        """funcname is name the function you want to use(can be either string, or functions.py function).
        if combotags is true then a combobox with tags that the user can choose from are shown.
        userargs is the default values you want to fill the controls in the dialog with
        [make sure they don't exceed the number of arguments of funcname]."""
        QWidget.__init__(self,parent)
        identifier = QuotedString('"') | Combine(Word
            (alphanums + ' !"#$%&\'()*+-./:;<=>?@[\\]^_`{|}~'))
        tags = delimitedList(identifier)
        self.func = Function(funcname)
        docstr = self.func.doc[1:]
        self.vbox = QVBoxLayout()
        self.retval = []
        self._combotags = []        

        if showcombo:
            fields = ['__all'] + sorted(INFOTAGS) + showcombo + gettaglist()
        else:
            fields = ['__selected', '__all'] + sorted(INFOTAGS) + gettaglist()

        self.tagcombo = QComboBox(self)
        tooltip = translate('Functions Dialog', """<p>Fields that will
            get written to.</p>

            <ul>
            <li>Enter a list of comma-separated fields
            eg. <b>artist, title, album</b></li>
            <li>Use <b>__selected</b> to write only to the selected cells.</li>
            <li>Combinations like <b>__selected, artist, title</b> are
                allowed.</li>
            <li>But using <b>__selected</b> in Actions is <b>not</b>.</li>
            <li>'~' will write to all the the fields, except what follows it
            . Eg <b>~artist, title</b> will write to all but the artist and
            title fields found in the selected files.<li>
            </ul>""")
        self.tagcombo.setToolTip(tooltip)
        self.tagcombo.setEditable(True)
        self.tagcombo.setAutoCompletionCaseSensitivity(Qt.CaseSensitive)
        self.tagcombo.addItems(fields)
        self._combotags = showcombo
        
        self.connect(self.tagcombo,
            SIGNAL('editTextChanged(const QString&)'), self.showexample)

        if self.func.function not in functions.no_fields:
            label = QLabel(translate('Defaults', "&Fields"))
            self.vbox.addWidget(label)
            self.vbox.addWidget(self.tagcombo)
            label.setBuddy(self.tagcombo)
        else:
            self.tagcombo.setVisible(False)
        self.example = example
        self._text = text

        if self.func.function in functions_dialogs.dialogs:
            vbox = QVBoxLayout()
            vbox.addWidget(self.tagcombo)
            self.widget = functions_dialogs.dialogs[self.func.function](self)
            vbox.addWidget(self.widget)
            vbox.addStretch()
            self.setLayout(vbox)
            self.setMinimumSize(self.sizeHint())

            self.setArguments(default_fields, userargs)
            return
        else:
            self.widget = None

        self.textcombos = []
        #Loop that creates all the controls
        self.controls = []
        for argno, line in enumerate(docstr):
            args = tags.parseString(line)
            label = args[0]
            ctype = args[1]
            default = args[2:]
            
            control, func, label = self._createControl(label, ctype, default)

            self.retval.append(func)
            self.controls.append(control)
            self.connect(control, self.signals[ctype], self.showexample)

            if label:
                self.vbox.addWidget(label)
            self.vbox.addWidget(control)

        self.setArguments(default_fields, userargs)
            
        self.vbox.addStretch()
        self.setLayout(self.vbox)
        self.setMinimumSize(self.sizeHint())

    def argValues(self):
        """Returns the values in the windows controls.
        The last argument is the tags value.
        Also sets self.func's arg and tag values."""

        if self.widget:
            newargs = self.widget.arguments()
        else:
            newargs = []
            for method in self.retval:
                if method.__name__ == 'checkState':
                    if method() == Qt.Checked:
                        newargs.append(True)
                    elif (method() == Qt.PartiallyChecked) or (method() == Qt.Unchecked):
                        newargs.append(False)
                else:
                    if isinstance(method(), (int, long)):
                        newargs.append(method())
                    else:
                        newargs.append(unicode(method()))
            [z.save() for z in self.textcombos]
        self.func.setArgs(newargs)

        fields = [z.strip() for z in
            unicode(self.tagcombo.currentText()).split(",") if z]

        if self.func.function in functions.no_fields:
            self.func.setTag(['just nothing to do with this'])
        else:
            self.func.setTag(fields)
        return newargs + fields

    def _createControl(self, label, ctype, default=None):
        if ctype == 'text':
            control = self._controls['text'](label, parent = self)
        else:
            control = self._controls[ctype](self)

        if ctype == 'combo':
            func = control.currentText
            if default:
                control.addItems(map(
                    lambda d: translate('Functions', d), default))
        elif ctype == 'text':
            self.textcombos.append(control)
            func = control.currentText
            if default:
                control.setEditText(default[0])
        elif ctype == 'check':
            func = control.checkState
            if default:
                if default[0] == "True" or default[0] is True:
                    control.setChecked(True)
                else:
                    control.setChecked(False)
            control.setText(label)

        if ctype != 'check':
            label = QLabel(translate('Functions', label))
            label.setBuddy(control)
        else:
            label = None

        return control, func, label

    def loadSettings(self, filename=None):
        if filename is None:
            filename = FUNC_SETTINGS
        cparser = PuddleConfig(filename)
        function = self.func.function
        section = '%s_%s' % (function.__module__, function.__name__)
        arguments = cparser.get(section, 'arguments', [])
        fields = cparser.get(section, 'fields', [])
        if not fields:
            fields = None
        self.setArguments(fields, arguments)

    def saveSettings(self, filename=None):
        if not filename:
            filename = FUNC_SETTINGS
        function = self.func.function
        section = '%s_%s' % (function.__module__, function.__name__)

        cparser = PuddleConfig(filename)
        args = self.argValues()
        cparser.set(section, 'arguments', self.func.args)
        cparser.set(section, 'fields', self.func.tag)

    def showexample(self, *args, **kwargs):
        self.argValues()
        if self.example is not None:
            audio = self.example
            try:
                if self.func.function in functions.no_preview:
                    self.emit(SIGNAL('updateExample'), 
                        translate('Functions Dialog',
                            'No preview for is shown for this function.'))
                    return
                fields = findfunc.parse_field_list(self.func.tag, audio, self._combotags)
                files = status['selectedfiles']
                files = unicode(len(files)) if files else u'1'
                state = {'__counter': u'1', '__total_files': files}
                val = findfunc.runAction([self.func], audio, state, fields)
            except findfunc.ParseError, e:
                val = u'<b>%s</b>' % (e.message)
            if val is not None:
                self.emit(SIGNAL('updateExample'), val)
            else:
                self.emit(SIGNAL('updateExample'),
                    translate('Functions Dialog', '<b>No change</b>'))

    def _sanitize(self, ctype, value):
        if ctype in ['combo', 'text']:
            return value
        elif ctype == 'check':
            if value is True or value == 'True':
                return True
            else:
                return False
        elif ctype == 'spinbox':
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

    def setArguments(self, fields=None, args=None):
        if fields is not None:
            text = u', '.join(fields)
            index = self.tagcombo.findText(text)
            if index != -1:
                self.tagcombo.setCurrentIndex(index)
            else:
                self.tagcombo.insertItem(0, text)
                self.tagcombo.setCurrentIndex(0)
            self.tagcombo.setEditText(text)

        if not args:
            return

        if self.widget:
            self.widget.setArguments(*args)
            return

        for argument, control in zip(args, self.controls):
            if isinstance(control, QComboBox):
                index = control.findText(argument)
                if index != -1:
                    control.setCurrentIndex(index)
            elif isinstance(control, PuddleCombo):
                control.setEditText(argument)
            elif isinstance(control, QCheckBox):
                control.setChecked(self._sanitize('check', argument))
            elif isinstance(control, QSpinBox):
                control.setValue(self._sanitize('spinbox', argument))

class CreateFunction(QDialog):
    """A dialog to allow the creation of functions using only one window and a QStackedWidget.
    For each function in functions, a dialog is created and displayed in the stacked widget."""
    def __init__(self, prevfunc = None, showcombo = True, parent = None, example = None, text = None):
        """tags is a list of the tags you want to show in the FunctionDialog.
        Each item should be in the form (DisplayName, tagname) as used in audioinfo.
        prevfunc is a Function object that is to be edited."""
        QDialog.__init__(self,parent)
        self.setWindowTitle(translate('Functions Dialog', "Functions"))
        winsettings('createfunction', self)

        self.realfuncs = []
        #Get all the function from the functions module.
        for z, funcname in functions.functions.items():
            if isinstance(funcname, PluginFunction):
                self.realfuncs.append(funcname)
            elif callable(funcname) and (not (funcname.__name__.startswith("__") or (funcname.__doc__ is None))):
                self.realfuncs.append(z)

        funcnames = sorted([(Function(z).funcname, z) for z in  self.realfuncs])
        self.realfuncs = [z[1] for z in funcnames]

        self.vbox = QVBoxLayout()
        self.functions = QComboBox()
        self.functions.addItems(map(lambda x: translate('Functions', x[0]),
            funcnames))
        self.vbox.addWidget(self.functions)

        self.stack = QStackedWidget()
        self.vbox.addWidget(self.stack)
        self.okcancel = OKCancel()

        self.mydict = {}    #Holds the created windows in the form self.functions.index: window
        self.setLayout(self.vbox)
        self.setMinimumHeight(self.sizeHint().height())
        self.connect(self.okcancel, SIGNAL("ok"), self.okClicked)
        self.connect(self.okcancel, SIGNAL('cancel'), self.close)
        
        self.example = example
        self._text = text
        if showcombo is True or not showcombo:
            self.showcombo = []
        else:
            self.showcombo = showcombo
            
        self.exlabel = ScrollLabel('')

        if prevfunc is not None:
            index = self.functions.findText(prevfunc.funcname)
            if index >= 0:
                self.functions.setCurrentIndex(index)
                self.createWindow(index, prevfunc.args, prevfunc.tag)
        else:
            self.createWindow(0)

        self.connect(self.functions, SIGNAL("activated(int)"), self.createWindow)

        self.vbox.addWidget(self.exlabel)
        self.vbox.addLayout(self.okcancel)
        self.setLayout(self.vbox)

    def createWindow(self, index, fields = None, args = None):
        """Creates a Function dialog in the stack window
        if it doesn't exist already."""
        self.stack.setFrameStyle(QFrame.Box)
        if index not in self.mydict:
            what = FunctionDialog(self.realfuncs[index], self.showcombo, 
                fields, args, example=self.example, text=self._text)
            if args is None:
                what.loadSettings()
            self.mydict.update({index: what})
            self.stack.addWidget(what)
            self.connect(what, SIGNAL('updateExample'), self.updateExample)
        self.stack.setCurrentWidget(self.mydict[index])
        self.mydict[index].showexample()
        self.setMinimumHeight(self.sizeHint().height())
        if self.sizeHint().width() > self.width():
            self.setMinimumWidth(self.sizeHint().width())

    def okClicked(self, close=True):
        w = self.stack.currentWidget()
        w.argValues()
        if close:
            self.close()
        if self.showcombo:
            newtags = [z for z in w.func.tag if z not in self.showcombo]
            if newtags:
                settaglist(sorted(newtags + self.showcombo))
        for widget in self.mydict.values():
            widget.saveSettings()
        self.emit(SIGNAL("valschanged"), w.func)

    def updateExample(self, text):
        if not text:
            self.exlabel.setText(u'')
        else:
            self.exlabel.setText(displaytags(text))

class CreateAction(QDialog):
    "An action is defined as a collection of functions. This dialog serves the purpose of creating an action"
    def __init__(self, parent = None, prevfunctions = None, example = None):
        """tags is a list of the tags you want to show in the FunctionDialog.
        Each item should be in the form (DisplayName, tagname as used in audioinfo).
        prevfunction is the previous function that is to be edited."""
        QDialog.__init__(self, parent)
        self.setWindowTitle(translate('Actions', "Modify Action"))
        winsettings('editaction', self)
        self.grid = QGridLayout()

        self.listbox = ListBox()
        self.functions = []
        self.buttonlist = ListButtons()
        self.grid.addWidget(self.listbox, 0, 0)
        self.grid.addLayout(self.buttonlist, 0, 1)

        self.okcancel = OKCancel()
        #self.grid.addLayout(self.okcancel,1,0,1,2)
        self.setLayout(self.grid)
        self.example = example

        self.connect(self.okcancel, SIGNAL("cancel"), self.close)
        self.connect(self.okcancel, SIGNAL("ok"), self.okClicked)
        self.connect(self.buttonlist, SIGNAL("add"), self.add)
        self.connect(self.buttonlist, SIGNAL("edit"), self.edit)
        self.connect(self.buttonlist, SIGNAL("moveup"), self.moveUp)
        self.connect(self.buttonlist, SIGNAL("movedown"), self.moveDown)
        self.connect(self.buttonlist, SIGNAL("remove"), self.remove)
        self.connect(self.buttonlist, SIGNAL("duplicate"), self.duplicate)
        self.connect(self.listbox, SIGNAL("currentRowChanged(int)"), self.enableOK)
        self.connect(self.listbox, SIGNAL("itemDoubleClicked (QListWidgetItem *)"), self.edit)

        if prevfunctions is not None:
            self.functions = copy(prevfunctions)
            self.listbox.addItems([function.description() for
                function in self.functions])

        if example:
            self._examplelabel = ScrollLabel('')
            self.grid.addWidget(self._examplelabel,1,0)
            self.grid.setRowStretch(0,1)
            self.grid.setRowStretch(1,0)
            self.example = example
            self.updateExample()
            self.grid.addLayout(self.okcancel,2,0,1,2)
        else:
            self.grid.addLayout(self.okcancel,1,0,1,2)

    def updateExample(self):
        try:
            files = status['selectedfiles']
            files = unicode(len(files)) if files else u'1'
            state = {'__counter': u'1', '__total_files': files}
            tags = runAction(self.functions, self.example, state)
            self._examplelabel.setText(displaytags(tags))
        except findfunc.ParseError, e:
            self._examplelabel.setText(e.message)

    def enableOK(self, val):
        if val == -1:
            [button.setEnabled(False) for button in self.buttonlist.widgets[1:]]
        else:
            [button.setEnabled(True) for button in self.buttonlist.widgets[1:]]

    def moveDown(self):
        self.listbox.moveDown(self.functions)

    def moveUp(self):
        self.listbox.moveUp(self.functions)

    def remove(self):
        self.listbox.removeSelected(self.functions)
        self.updateExample()

    def add(self):
        self.win = CreateFunction(None, parent = self, example = self.example)
        self.win.setModal(True)
        self.win.show()
        self.connect(self.win, SIGNAL("valschanged"), self.addBuddy)

    def edit(self):
        self.win = CreateFunction(self.functions[self.listbox.currentRow()],
            parent=self, example = self.example)
        self.win.setModal(True)
        self.win.show()
        self.connect(self.win, SIGNAL("valschanged"), self.editBuddy)

    def editBuddy(self, func):
        self.listbox.currentItem().setText(func.description())
        self.functions[self.listbox.currentRow()] = func
        self.updateExample()

    def addBuddy(self, func):
        self.listbox.addItem(func.description())
        self.functions.append(func)
        self.updateExample()

    def okClicked(self):
        self.close()
        self.emit(SIGNAL("donewithmyshit"), self.functions)

    def duplicate(self):
        self.win = CreateFunction(self.functions[self.listbox.currentRow()],
            parent=self, example = self.example)
        self.win.setModal(True)
        self.win.show()
        self.connect(self.win, SIGNAL("valschanged"), self.addBuddy)

class ActionWindow(QDialog):
    """Just a dialog that allows you to add, remove and edit actions
    On clicking OK, a signal "donewithmyshit" is emitted.
    It returns a list of lists.
    Each element of a list contains one complete action. While
    the elements of that action are just normal Function objects."""
    def __init__(self, parent = None, example = None, quickaction = None):
        """tags are the tags to be shown in the FunctionDialog"""
        QDialog.__init__(self,parent)
        self.setWindowTitle(translate('Actions', "Actions"))
        winsettings('actions', self)
        self._shortcuts = []
        self._quickaction = quickaction
        self.listbox = ListBox()
        self.listbox.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.listbox.setEditTriggers(QAbstractItemView.EditKeyPressed)

        self.example = example

        self.funcs = self.loadActions()
        cparser = PuddleConfig()
        to_check = cparser.get('actions', 'checked', [])
        for z in self.funcs:
            func_name = self.funcs[z][1]
            item = QListWidgetItem(func_name)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            if func_name in to_check:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.listbox.addItem(item)

        self.okcancel = OKCancel()
        self.okcancel.ok.setDefault(True)
        x = QAction(translate('Actions', 'Assign &Shortcut'), self)
        self.shortcutButton = QToolButton()
        self.shortcutButton.setDefaultAction(x)
        x.setToolTip(translate('Actions', '''<p>Creates a
            shortcut for the checked actions on the Actions menu.
            Use Edit Shortcuts (found by pressing down on this button)
            to edit shortcuts after the fact.</p>'''))
        menu = QMenu(self)
        edit_shortcuts = QAction(translate('Actions', 'Edit Shortcuts'), menu)
        self.connect(edit_shortcuts, SIGNAL('triggered()'), self.editShortcuts)
        menu.addAction(edit_shortcuts)
        self.shortcutButton.setMenu(menu)

        self.okcancel.insertWidget(0, self.shortcutButton)
        self.grid = QGridLayout()

        self.buttonlist = ListButtons()

        self.grid.addWidget(self.listbox,0, 0)
        self.grid.setRowStretch(0, 1)
        self.grid.addLayout(self.buttonlist, 0,1)
        self.setLayout(self.grid)

        connect = lambda obj, sig, slot: self.connect(obj, SIGNAL(sig), slot)

        connect(self.okcancel, "ok" , self.okClicked)
        connect(self.okcancel, "cancel",self.close)
        connect(self.buttonlist, "add", self.add)
        connect(self.buttonlist, "edit", self.edit)
        connect(self.buttonlist, "moveup", self.moveUp)
        connect(self.buttonlist, "movedown", self.moveDown)
        connect(self.buttonlist, "remove", self.remove)
        connect(self.buttonlist, "duplicate", self.duplicate)
        connect(self.listbox, "itemDoubleClicked (QListWidgetItem *)", self.edit)
        connect(self.listbox, "currentRowChanged(int)", self.enableListButtons)
        connect(self.listbox, "itemChanged(QListWidgetItem *)", self.renameAction)
        connect(self.listbox, "itemChanged(QListWidgetItem *)", self.enableOK)
        connect(self.shortcutButton, 'clicked()', self.createShortcut)

        self._examplelabel = ScrollLabel('')
        self.grid.addWidget(self._examplelabel, 1, 0, 1,-1)
        self.grid.setRowStretch(1, 0)
        if example is None:
            self._examplelabel.hide()
        self.connect(self.listbox, SIGNAL('itemChanged (QListWidgetItem *)'),
            self.updateExample)
        self.grid.addLayout(self.okcancel,2,0,1,2)
        self.updateExample()
        self.enableOK(None)

    def createShortcut(self):
        names, funcs = self.checked()
        (name, ok) = ShortcutName(self.shortcutNames(), names[0]).getText()
        
        if name and ok:
            import puddlestuff.puddletag
            shortcuts = [unicode(z.shortcut().toString()) for z in
                puddlestuff.puddletag.status['actions']]
            (shortcut, ok) = ShortcutDialog(shortcuts).getShortcut()
            name = unicode(name)
            filenames = [self.funcs[row][2] for row in self.checkedRows()]
            
            from puddlestuff.action_shortcuts import create_action_shortcut, save_shortcut
            if shortcut and ok:
                create_action_shortcut(name, filenames, shortcut, add=True)
            else:
                create_action_shortcut(name, filenames, add=True)
            save_shortcut(name, filenames)

    def editShortcuts(self):
        import action_shortcuts
        win = action_shortcuts.ShortcutEditor(True, self, True)
        win.setModal(True)
        win.show()

    def moveUp(self):
        self.listbox.moveUp(self.funcs)

    def moveDown(self):
        self.listbox.moveDown(self.funcs)

    def remove(self):
        cparser = PuddleConfig()
        listbox = self.listbox
        rows = sorted([listbox.row(item) for item in listbox.selectedItems()])
        for row in rows:
            filename = self.funcs[row][2]
            os.rename(filename, filename + '.deleted')
        self.listbox.removeSelected(self.funcs)
        
        funcs = {}
        for i, key in enumerate(sorted(self.funcs)):
            funcs[i] = self.funcs[key]
        self.funcs = funcs

    def enableListButtons(self, val):
        if val == -1:
            [button.setEnabled(False) for button in self.buttonlist.widgets[1:]]
        else:
            [button.setEnabled(True) for button in self.buttonlist.widgets[1:]]


    def enableOK(self, val):
        item = self.listbox.item
        enable = [row for row in range(self.listbox.count()) if
                    item(row).checkState() == Qt.Checked]
        if enable:
            self.okcancel.ok.setEnabled(True)
            self.shortcutButton.setEnabled(True)
        else:
            self.okcancel.ok.setEnabled(False)
            self.shortcutButton.setEnabled(False)
    
    def renameAction(self, item):
        row = self.listbox.row(item)
        name = unicode(item.text())
        if name != self.funcs[row][1]:
            self.saveAction(name, self.funcs[row][0], self.funcs[row][2])

    def loadActions(self):
        from glob import glob
        basename = os.path.basename

        funcs = {}
        cparser = PuddleConfig()
        set_value = partial(cparser.set, 'puddleactions')
        get_value = partial(cparser.get, 'puddleactions')
        
        firstrun = get_value('firstrun', True)
        set_value('firstrun', False)
        convert = get_value('convert', True)
        order = get_value('order', [])

        if convert:
            set_value('convert', False)
            findfunc.convert_actions(SAVEDIR, ACTIONDIR)
            if order:
                old_order = dict([(basename(z), i) for i,z in  
                    enumerate(order)])
                files = glob(os.path.join(ACTIONDIR, u'*.action'))
                order = {}
                for f in files:
                    try:
                        order[old_order[basename(f)]] = f
                    except KeyError:
                        pass
                order = [z[1] for z in sorted(order.items())]
                set_value('order', order)

        files = glob(os.path.join(ACTIONDIR, u'*.action'))
        if firstrun and not files:
            filenames = [':/caseconversion.action', ':/standard.action']
            files = map(open_resourcefile, filenames)
            set_value('firstrun', False)

            for fileobj, filename in zip(files, filenames):
                filename = os.path.join(ACTIONDIR, filename[2:])
                f = open(filename, 'w')
                f.write(fileobj.read())
                f.close()
            files = glob(os.path.join(ACTIONDIR, u'*.action'))

        files = [z for z in order if z in files] + \
            [z for z in files if z not in order]

        for i, f in enumerate(files):
            action = findfunc.load_action(f)
            funcs[i] = [action[0], action[1], f]
        return funcs

    def updateExample(self, *args):
        if self.example is None:
            self._examplelabel.hide()
            return
        l = self.listbox
        items = [l.item(z) for z in range(l.count())]
        selectedrows = [i for i,z in enumerate(items) if z.checkState() == Qt.Checked]
        if selectedrows:
            tempfuncs = [self.funcs[row][0] for row in selectedrows]
            funcs = []
            [funcs.extend(func) for func in tempfuncs]
            try:
                files = status['selectedfiles']
                files = unicode(len(files)) if files else u'1'
                state = {'__counter': u'1', '__total_files': files}
                if self._quickaction:
                    tags = runQuickAction(funcs, self.example, state, self._quickaction)
                else:
                    tags = runAction(funcs, self.example, state)

                self._examplelabel.show()
                self._examplelabel.setText(displaytags(tags))
            except findfunc.ParseError, e:
                self._examplelabel.show()
                self._examplelabel.setText(e.message)
        else:
            self._examplelabel.hide()

    def removeSpaces(self, text):
        for char in string.whitespace:
            text = text.replace(char, '')
        return text.lower()

    def saveAction(self, name, funcs, filename=None):
        cparser = PuddleConfig()
        if not filename:
            filename = os.path.join(ACTIONDIR, safe_name(name) + u'.action')
            base = os.path.splitext(filename)[0]
            i = 0
            while os.path.exists(filename):
                filename = u"%s_%d" % (base, i) + u'.action'
                i += 1
        findfunc.save_action(filename, name, funcs)
        return filename

    def add(self):
        (text, ok) = QInputDialog.getText (self,
            translate('Actions', "New Action"),
            translate('Actions', "Enter a name for the new action."),
            QLineEdit.Normal)
        if (ok is True) and text:
            item = QListWidgetItem(text)
            item.setCheckState(Qt.Unchecked)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.listbox.addItem(item)
        else:
            return
        win = CreateAction(self, example = self.example)
        win.setWindowTitle(translate('Actions', "Edit Action: ") + \
            self.listbox.item(self.listbox.count() - 1).text())
        win.setModal(True)
        win.show()
        self.connect(win, SIGNAL("donewithmyshit"), self.addBuddy)

    def addBuddy(self, funcs):
        name = unicode(self.listbox.item(self.listbox.count() - 1).text())
        filename = self.saveAction(name, funcs)
        self.funcs.update({self.listbox.count() - 1: [funcs, name, filename]})

    def edit(self):
        win = CreateAction(self, self.funcs[self.listbox.currentRow()][0], example = self.example)
        win.setWindowTitle(translate('Actions', "Edit Action: ") +
            self.listbox.currentItem().text())
        win.show()
        self.connect(win, SIGNAL("donewithmyshit"), self.editBuddy)

    def editBuddy(self, funcs):
        row = self.listbox.currentRow()
        self.saveAction(self.funcs[row][1], funcs, self.funcs[row][2])
        self.funcs[row][0] = funcs
        self.updateExample()

    def checked(self):
        selectedrows = self.checkedRows()
        tempfuncs = [self.funcs[row][0] for row in selectedrows]
        names = [self.funcs[row][1] for row in selectedrows]
        funcs = []
        [funcs.extend(func) for func in tempfuncs]
        return names, funcs

    def checkedRows(self):
        l = self.listbox
        items = [l.item(z) for z in range(l.count())]
        checked = [i for i,z in enumerate(items) if
            z.checkState() == Qt.Checked]
        return checked

    def saveChecked(self):
        cparser = PuddleConfig()
        cparser.set('actions', 'checked', self.checked()[0])

    def saveOrder(self):
        funcs = self.funcs
        cparser = PuddleConfig()
        order = [funcs[index][2] for index in sorted(funcs)]
        lastorder = cparser.get('puddleactions', 'order', [])
        if lastorder == order:
            return
        cparser.set('puddleactions', 'order', order)
        self.emit(SIGNAL('actionOrderChanged'))

    def close(self):
        self.saveOrder()
        QDialog.close(self)

    def okClicked(self, close=True):
        """When clicked, save the current contents of the listbox and the associated functions"""
        names, funcs = self.checked()
        cparser = PuddleConfig()
        cparser.set('actions', 'checked', names)
        if close:
            self.close()
        self.emit(SIGNAL('checkedChanged'), self.checkedRows())
        self.emit(SIGNAL("donewithmyshit"), funcs)

    def duplicate(self):
        l = self.listbox
        if len(l.selectedItems()) > 1:
            return
        row = l.currentRow()
        oldname = self.funcs[row][1]
        (text, ok) = QInputDialog.getText (self,
            translate('Actions', "Copy %s action" % oldname),
            translate('Actions', "Enter a name for the new action."),
            QLineEdit.Normal)
        if not (ok and text):
            return
        funcs = copy(self.funcs[row][0])
        name = unicode(text)
        win = CreateAction(self, funcs, example = self.example)
        win.setWindowTitle(translate('Actions', "Edit Action: %s") % name)
        win.show()
        dupebuddy = partial(self.duplicateBuddy, name)
        self.connect(win, SIGNAL("donewithmyshit"), dupebuddy)

    def duplicateBuddy(self, name, funcs):
        item = QListWidgetItem(name)
        item.setCheckState(Qt.Unchecked)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.listbox.addItem(item)
        filename = self.saveAction(name, funcs)
        self.funcs.update({self.listbox.count() - 1: [funcs, name, filename]})

    def shortcutNames(self):
        from action_shortcuts import load_settings
        return [name for name, filename in load_settings()[1]]
        

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("Puddle Inc.")
    app.setApplicationName("puddletag")
    qb = ActionWindow([(u'Path', u'__path'), ('Artist', 'artist'), ('Title', 'title'), ('Album', 'album'), ('Track', 'track'), ('Length', '__length'), (u'Year', u'date')])
    qb.show()
    app.exec_()

#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
# plugins.py
#
# Copyright 2013, 2014 Patrick Ulbrich <zulu99@gmx.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301, USA.
#

import os
import imp
import inspect
import logging

from Mailnag.common.config import cfg_folder
from Mailnag.common.dist_cfg import LIB_DIR

PLUGIN_LIB_PATH = os.path.join(LIB_DIR, 'plugins')
PLUGIN_USER_PATH = os.path.join(cfg_folder, 'plugins')
PLUGIN_PATHS = [ PLUGIN_LIB_PATH, PLUGIN_USER_PATH ]

#
# All known hook types.
#
# TODO : make this class an enum 
# when Mailnag is ported to python3
class HookTypes:
	# func signature: 
	# IN:	List of loaded accounts
	# OUT:	None
	ACCOUNTS_LOADED = 'accounts-loaded'
	# func signature: 
	# IN:	None
	# OUT:	None
	MAIL_CHECK = 'mail-check'
	# func signature: 
	# IN:	new mails, all mails
	# OUT:	None
	MAILS_ADDED = 'mails-added'
	# func signature:
	# IN:	remaining mails
	# OUT:	None
	MAILS_REMOVED = 'mails-removed'
	# func signature:
	# IN:	all mails
	# OUT:	filtered mails
	FILTER_MAILS = 'filter-mails'


#
# Registry class for plugin hooks.
#
# Registered hook functions must not block the mailnag daemon.
# Hook functions with an execution time > 1s should be 
# implemented non-blocking (i. e. asynchronously).
class HookRegistry:
	def __init__(self):
		self._hooks = {
			HookTypes.ACCOUNTS_LOADED	: [],
			HookTypes.MAIL_CHECK		: [],
			HookTypes.MAILS_ADDED		: [],
			HookTypes.MAILS_REMOVED		: [],
			HookTypes.FILTER_MAILS 		: []
		}
	
	
	def register_hook_func(self, hooktype, func):
		self._hooks[hooktype].append(func)
	
	
	def unregister_hook_func(self, hooktype, func):
		self._hooks[hooktype].remove(func)
	
	
	def get_hook_funcs(self, hooktype):
		return self._hooks[hooktype]


# Abstract base class for a MailnagController instance 
# passed to plugins.
class MailnagController:
	# Returns a HookRegistry object.
	def get_hooks(self):					pass
	# Shuts down the Mailnag process.
	# May throw an InvalidOperationException.
	def shutdown(self):						pass
	# Enforces a manual mail check.
	# May throw an InvalidOperationException.
	def check_for_mails(self):				pass
	# Marks the mail with specified mail_id as read.
	# May throw an InvalidOperationException.
	def mark_mail_as_read(self, mail_id):	pass


#
# Mailnag Plugin base class
#
class Plugin:
	def __init__(self):
		# Plugins shouldn't do anything in the constructor. 
		# They are expected to start living if they are actually 
		# enabled (i.e. in the enable() method).
		# Plugin data isn't enabled yet and call to methods like
		# get_mailnag_controller() or get_config().
		pass
	
	#
	# Abstract methods, 
	# to be overriden by derived plugin types.
	#
	def enable(self):
		# Plugins are expected to
		# register all hooks here.
		raise NotImplementedError
	
	
	def disable(self):
		# Plugins are expected to
		# unregister all hooks here, 
		# free all allocated resources, 
		# and terminate threads (if any).
		raise NotImplementedError
	
	
	def get_manifest(self):
		# Plugins are expected to
		# return a tuple of the following form:
		# (name, description, version, author, mandatory).
		raise NotImplementedError
	
	
	def get_default_config(self):
		# Plugins are expected to return a
		# dictionary with default values.
		raise NotImplementedError
	
	
	def has_config_ui(self):
		# Plugins are expected to return True if
		# they provide a configuration widget,
		# otherwise they must return False.
		raise NotImplementedError
	
	
	def get_config_ui(self):
		# Plugins are expected to
		# return a GTK widget here.
		# Return None if the plugin 
		# does not need a config widget.
		raise NotImplementedError

	
	def load_ui_from_config(self, config_ui):
		# Plugins are expected to
		# load their config values (get_config()) 
		# in the widget returned by get_config_ui().
		raise NotImplementedError
	
	
	def save_ui_to_config(self, config_ui):
		# Plugins are expected to
		# save the config values of the widget
		# returned by get_config_ui() to their config
		# (get_config()).
		raise NotImplementedError
	
	
	#
	# Public methods
	#
	def init(self, modname, cfg, mailnag_controller):
		config = {}
		
		# try to load plugin config
		if cfg.has_section(modname):
			for name, value in cfg.items(modname):
				config[name] = value
		
		# sync with default config
		default_config = self.get_default_config()
		for k, v in default_config.iteritems():
			if not config.has_key(k):
				config[k] = v
		
		self._modname = modname
		self._config = config
		self._mailnag_controller = mailnag_controller
	
	
	def get_name(self):
		name = self.get_manifest()[0]
		return name
	
	
	def get_modname(self):
		return self._modname
	
	
	def get_config(self):
		return self._config
	
	
	#
	# Protected methods
	#
	def get_mailnag_controller(self):
		return self._mailnag_controller
	
	
	#
	# Static methods
	#
	
	# Note : Plugin instances do not own 
	# a reference to MailnagController object 
	# when instantiated in *config mode*.
	@staticmethod
	def load_plugins(cfg, mailnag_controller = None, filter_names = None):
		plugins = []
		plugin_types = Plugin._load_plugin_types()
		
		for modname, t in plugin_types:			
			try:
				if (filter_names == None) or (modname in filter_names):
					p = t()
					p.init(modname, cfg, mailnag_controller)
					plugins.append(p)
			except:
				logging.exception("Failed to instantiate plugin '%s'" % modname)
		
		return plugins
	
	
	@staticmethod
	def _load_plugin_types():
		plugin_types = []
		
		for path in PLUGIN_PATHS:
			if not os.path.exists(path):
				continue
			
			for f in os.listdir(path):
				mod = None
				modname, ext = os.path.splitext(f)
				
				try:
					if ext.lower() == '.py':
						if not os.path.exists(os.path.join(path, modname + '.pyc')):
							mod = imp.load_source(modname, os.path.join(path, f))
					elif ext.lower() == '.pyc':
						mod = imp.load_compiled(modname, os.path.join(path, f))
				
					if mod != None:
						for t in dir(mod):
							t = getattr(mod, t)
							if inspect.isclass(t) and \
								(inspect.getmodule(t) == mod) and \
								issubclass(t, Plugin):
								plugin_types.append((modname, t))
						
				except:
					logging.exception("Error while opening plugin file '%s'" % f)
		
		return plugin_types

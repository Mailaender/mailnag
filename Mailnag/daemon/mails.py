#!/usr/bin/env python2
# -*- coding: utf-8 -*-
#
# mails.py
#
# Copyright 2011 - 2013 Patrick Ulbrich <zulu99@gmx.net>
# Copyright 2011 Leighton Earl <leighton.earl@gmx.com>
# Copyright 2011 Ralf Hersel <ralf.hersel@gmx.net>
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

import time
import email
import os
import logging
import hashlib

from common.i18n import _
from common.config import cfg_folder
from email.header import decode_header


#
# Mail class
#
class Mail:
	def __init__(self, datetime, subject, sender, id, account_id):
		self.datetime = datetime
		self.subject = subject
		self.sender = sender
		self.id = id
		self.account_id = account_id


#
# MailCollector class
#
class MailCollector:
	def __init__(self, cfg, accounts):
		self._cfg = cfg
		self._accounts = accounts
		
		
	def collect_mail(self, sort = True):
		mail_list = []
		mail_ids = []
		
		for acc in self._accounts:
			# get server connection for this account
			srv = acc.get_connection(use_existing = True)
			if srv == None:
				continue
			elif acc.imap: # IMAP
				if len(acc.folder.strip()) == 0:
					folder_list = ["INBOX"]
				else:
					folder_list = acc.folder.split(',')
					
				for folder in folder_list:	
					folder = folder.strip()
					if len(folder) == 0:
						continue
					
					# select IMAP folder
					srv.select(folder, readonly = True)
					try:
						status, data = srv.search(None, 'UNSEEN') # ALL or UNSEEN
					except:
						logging.warning('Folder %s does not exist.', folder)
						continue

					if status != 'OK' or None in [d for d in data]:
						logging.debug('Folder %s in status %s | Data: %s', (folder, status, data))
						continue # Bugfix LP-735071
					for num in data[0].split():
						typ, msg_data = srv.fetch(num, '(BODY.PEEK[HEADER])') # header only (without setting READ flag)
						for response_part in msg_data:
							if isinstance(response_part, tuple):
								try:
									msg = email.message_from_string(response_part[1])
								except:
									logging.debug("Couldn't get IMAP message.")
									continue
								
								sender, subject, datetime, hash_datetime = self._get_header(msg)
																
								# Note: mails received in the same folder with identical sender and subject but *no datetime* 
								# will have the same hash id, i.e. only the first mail is notified. (Should happen very rarely).
								id = hashlib.md5((acc.server + folder + acc.user + sender[1] + subject + hash_datetime)
									.encode('utf-8')).hexdigest()
					
						# prevent duplicates caused by Gmail labels
						if id not in mail_ids:
							mail_list.append(Mail(datetime, subject, \
								sender, id, acc.get_id()))
							mail_ids.append(id)
				
				# don't close IMAP idle connections
				if not acc.idle:
					srv.close()
					srv.logout()
			else: # POP
				# number of mails on the server
				mail_total = len(srv.list()[1])
				for i in range(1, mail_total + 1): # for each mail
					try:
						# header plus first 0 lines from body
						message = srv.top(i, 0)[1]
					except:
						logging.debug("Couldn't get POP message.")
						continue
					
					# convert list to string
					message_string = '\n'.join(message)
					
					try:
						# put message into email object and make a dictionary
						msg = dict(email.message_from_string(message_string))
					except:
						logging.debug("Couldn't get msg from POP message.")
						continue
					
					sender, subject, datetime, hash_datetime = self._get_header(msg)
					
					# Note: mails received on the same server with identical sender and subject but *no datetime* 
					# will have the same hash id, i.e. only the first mail is notified. (Should happen very rarely).
					id = hashlib.md5((acc.server + acc.user + sender[1] + subject + hash_datetime)
						.encode('utf-8')).hexdigest()
					
					mail_list.append(Mail(datetime, subject, sender, \
						id, acc.get_id()))

				# disconnect from Email-Server
				srv.quit()
		
		# sort mails
		if sort:
			mail_list = sort_mails(mail_list, sort_desc = True)
		
		return mail_list


	def _get_header(self, msg_dict):
		try:
			content = self._get_header_field(msg_dict, 'From')
			sender = self._format_header_field('sender', content)
		except:
			sender = ('', '')

		try:
			content = self._get_header_field(msg_dict, 'Subject')
		except:
			content = _('No subject')
		try:
			subject = self._format_header_field('subject', content)
		except:
			subject = ''
		
		try:
			content = self._get_header_field(msg_dict, 'Date')
			datetime = self._format_header_field('date', content)
			hash_datetime = str(datetime)
		except:
			logging.warning('Using current time for email date.')
			# current time to seconds
			datetime = int(time.time())
			hash_datetime = ''
			
		return (sender, subject, datetime, hash_datetime)
	
	
	def _get_header_field(self, msg_dict, key):
		if msg_dict.has_key(key):
			value = msg_dict[key]
		elif msg_dict.has_key(key.lower()):
			value = msg_dict[key.lower()]
		else:
			logging.debug("Couldn't get %s from message." % key)
			raise KeyError
		
		return value

	
	# format sender, date, subject etc.
	def _format_header_field(self, field_name, content):
		if field_name == 'sender':
			# get the two parts of the sender
			sender_real, sender_addr = email.utils.parseaddr(content)
			sender_real = self._convert(sender_real)
			sender_addr = self._convert(sender_addr)
			# create decoded tupel
			return (sender_real, sender_addr)

		if field_name == 'date':
			# make a 10-tupel (UTC)
			parsed_date = email.utils.parsedate_tz(content)
			# convert 10-tupel to seconds incl. timezone shift
			return email.utils.mktime_tz(parsed_date)

		if field_name == 'subject':
			return self._convert(content)


	# decode and concatenate multi-coded header parts
	def _convert(self, raw_content):
		# replace newline by space
		content = raw_content.replace('\n',' ')
		# workaround a bug in email.header.decode_header()
		content = content.replace('?==?','?= =?')
		# list of (text_part, charset) tupels
		tupels = decode_header(content)
		content_list = []
		# iterate trough parts
		for text, charset in tupels:
			# set default charset for decoding
			if charset == None: charset = 'latin-1'
			# replace non-decodable chars with 'nothing'
			content_list.append(text.decode(charset, 'ignore'))
		
		# insert blanks between parts
		decoded_content = u' '.join(content_list)
		# get rid of whitespace
		decoded_content = decoded_content.strip()

		return decoded_content


#
# MailSyncer class
#
class MailSyncer:
	def __init__(self, cfg):
		self._cfg = cfg
		self._mails_by_account = {}
		self._mail_list = []
	
	
	def sync(self, accounts):
		needs_rebuild = False
		
		# collect mails from given accounts
		rcv_lst = MailCollector(self._cfg, accounts).collect_mail(sort = False)
	
		# group received mails by account
		tmp = {}
		for acc in accounts:
			tmp[acc.get_id()] = {}
		for mail in rcv_lst:
			tmp[mail.account_id][mail.id] = mail
	
		# compare current mails against received mails
		# and remove those that are gone (probably opened in mail client).
		for acc_id in self._mails_by_account.iterkeys():
			if acc_id in tmp:
				del_ids = []
				for mail_id in self._mails_by_account[acc_id].iterkeys():
					if not (mail_id in tmp[acc_id]):
						del_ids.append(mail_id)
						needs_rebuild = True
				for mail_id in del_ids:
					del self._mails_by_account[acc_id][mail_id]
	
		# compare received mails against current mails
		# and add new mails.
		for acc_id in tmp:
			if not (acc_id in self._mails_by_account):
				self._mails_by_account[acc_id] = {}
			for mail_id in tmp[acc_id]:
				if not (mail_id in self._mails_by_account[acc_id]):
					self._mails_by_account[acc_id][mail_id] = tmp[acc_id][mail_id]
					needs_rebuild = True
		
		# rebuild and sort mail list
		if needs_rebuild:
			self._mail_list = []
			for acc_id in self._mails_by_account:
				for mail_id in self._mails_by_account[acc_id]:
					self._mail_list.append(self._mails_by_account[acc_id][mail_id])
			self._mail_list = sort_mails(self._mail_list, sort_desc = True)
		
		return self._mail_list


#
# sort_mails function
#
def sort_mails(mail_list, sort_desc = False):
	sort_list = []
	for mail in mail_list:
		sort_list.append([mail.datetime, mail])
	
	# sort asc
	sort_list.sort()
	if sort_desc:
		sort_list.reverse()

	# recreate mail_list
	mail_list = []
	for mail in sort_list:
		mail_list.append(mail[1])
	return mail_list


#
# Reminder class
#
class Reminder(dict):

	def load(self):
		# load last known messages from mailnag.dat
		dat_file = os.path.join(cfg_folder, 'mailnag.dat')
		
		if os.path.exists(dat_file):
			f = open(dat_file, 'r')	# reopen file
			for line in f:
				# remove CR at the end
				stripedline = line.strip()
				# get all items from one line in a list: ["mailid", show_only_new flag"]
				content = stripedline.split(',')
				try:
					# add to dict [id : flag]
					self[content[0]] = content[1]
				except IndexError:
					# no flags in mailnag.dat
					self[content[0]] = '0'
			f.close()


	# save mail ids to file
	def save(self, mail_list):
		if not os.path.exists(cfg_folder):
			os.makedirs(cfg_folder)
		
		dat_file = os.path.join(cfg_folder, 'mailnag.dat')
		f = open(dat_file, 'w')	# open for overwrite
		for m in mail_list:
			try:
				seen_flag = self[m.id]
			except KeyError:
				# id of a new mail is not yet known to reminder
				seen_flag = '0'
			# construct line: email_id, seen_flag
			line = m.id + ',' + seen_flag + '\n'
			f.write(line)
			self[m.id] = seen_flag
		f.close()


	# check if mail id is in reminder list
	def contains(self, id):
		return (id in self)


	# set seen flag for this email on True
	def set_to_seen(self, id):
		try:
			self[id] = '1'
		except KeyError:
			pass


	def unseen(self, id):
		try:
			flag = self[id]
			return (flag == '0')
		except KeyError:
			return True

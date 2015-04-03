from keypad import Keypad
from oled import OLED
from nfc_reader import NFCReader
from forkpi_db import ForkpiDB

import time
from math import ceil

from rfid_thread import *
from fingerprint_thread import *

class SpoonPi:
	# LOCKOUT TABLE columns [rfid_uid, incorrect_streak, lockout]
	COL_UID, COL_STREAK, COL_TIME_LEFT = list(range(3))

	def __init__(self):
		self.lockout_table = list()

		print('Loading OLED...')
		self.led = OLED()
		# print('Loading NFC Reader...')
		# self.nfc_reader = NFCReader()
		print('Loading keypad...')
		self.keypad = Keypad()
		print('Loading the ForkPi database...')
		self.db = ForkpiDB()
		print('Loading options...')
		self.attempt_limit = self.load_option('attempt_limit')
		self.lockout_time = self.load_option('lockout_time_minutes') * 60
		self.keypad_timeout = self.load_option('keypad_timeout_seconds')

	def load_option(self, name):
		value, default = self.db.fetch_option(name)
		if value.isdigit():
			print('  custom : {} = {}'.format(name, value))
			return int(value)
		else:
			print('  default: {} = {}'.format(name, default))
			return int(default)

	def allow_access(self, names, pin, rfid_uid):
		pin = '*' * len(pin) # convert pin to asterisks so pin is not exposed in the logs
		message = "Allowed PIN({}) UID({}) : {}".format(pin, rfid_uid, names)
		print(message)
		self.db.log_allowed(names=names, pin=pin, rfid_uid=rfid_uid)
		self.led.clear_display()
		self.led.puts("Access\ngranted")

	def deny_access(self, reason, pin, rfid_uid, led_message="Access\ndenied"):
		message = "Denied  PIN({}) UID({}) : {}".format(pin, rfid_uid, reason)
		print(message)
		self.db.log_denied(reason=reason, pin=pin, rfid_uid=rfid_uid)
		self.led.clear_display()
		self.led.puts(led_message)

	def pin_authentication(self):
		'''
		Returns (pin, timeout) where
		  pin = the pin entered (string)
		  timeout = whether the keypad timed out (boolean)
		'''
		pin = ''
		self.led.clear_display()
		self.led.puts("Enter PIN:\n")

		while True:
		    key = self.keypad.getch(timeout=self.keypad_timeout)
		    if key == Keypad.TIMEOUT:
		    	return pin, True
		    elif key.isdigit():
		        pin += str(key)
		        self.led.puts('*')
		    elif key == '*': # backspace
		    	pin = pin[:-1]
		    	self.led.puts('\b')
		    elif key == '#': # enter
		    	return pin, False

	def find_lockout_row(self, rfid_uid):
		lockout_row = None
		for row in self.lockout_table:
			if row[0] == rfid_uid:
				lockout_row = row
		if lockout_row is None:
			lockout_row = [rfid_uid, 0, 0]
			self.lockout_table.append(lockout_row)
		return lockout_row

	def update_lockout_timers(self, time_elapsed):
		for row in self.lockout_table:
			lockout_time_left = row[SpoonPi.COL_TIME_LEFT]
			was_locked_out = (lockout_time_left > 0)
			row[SpoonPi.COL_TIME_LEFT] = max(0, lockout_time_left - time_elapsed)
			if was_locked_out and row[SpoonPi.COL_TIME_LEFT] == 0:
				row[SpoonPi.COL_STREAK] = 0

	def run(self):
		"""
		Flow:
			Ask for RFID or Fingerprint
			If the RFID or Fingerprint is authorized, access granted.
			Else, ask for PIN, then check for auth.
			Notice that there's no three-factor auth.
			Because fuck that shit.
		"""
		
		# Start the RFID Thread
		rfid_thread = RfidThread()
		rfid_thread.start()

		# Start the Fingerprint Thread
		fingerprint_thread = FingerprintThread()
		fingerprint_thread.start()

		# Some initializations
		is_ask_for_pin = False
		is_resetting = False
		finger_id = 0
		rfid_uid = 0

		# LED initializations
		self.led.clear_display()
		self.led.puts("Swipe RFID\nor Finger")

		while True:

			# If the RFID thread goes: "An RFID card has been swiped!"
			if rfid_thread.is_found:

				# Ask the fingerprint thread to stop polling
				fingerprint_thread.is_not_polling = True

				# Grab the UID and do single-factor RFID authorization check:
				rfid_uid = rfid_thread.rfid_uid
				is_authorized, names = self.db.authorize(pin='', rfid_uid=rfid_uid)

				# If authorized, allow entry. else: Set the ask_for_pin flag = True
				if is_authorized:
					self.allow_access(names=names, pin='', rfid_uid=rfid_uid)
					is_resetting = True
				else:
					is_ask_for_pin = True

			# If the Fingerprint thread goes: "A new fingerprint has been found!"
			if fingerprint_thread.is_found:

				# Ask the RFID thread to stop polling
				rfid_thread.is_not_polling = True

				# Grab the ID of the fingerprint template
				finger_id = fingerprint_thread.finger_id

				# TODO: Check if there is single-factor auth for said fingerprint
				if False:
					is_resetting = True
				# Else, ask for PIN.
				else:
					# Temporary rfid for the currently working PIN + RFID authentication
					rfid_uid = "1234abcd"
					is_ask_for_pin = True

			# If somebody's asking for the PIN
			if is_ask_for_pin:

				# Grab the pin and do an authorization check
				pin, timed_out = self.pin_authentication()

				# TODO: Incorporate fingerprint in the authorization
				is_authorized, names = self.db.authorize(pin=pin, rfid_uid=rfid_uid)

				# If authorized, Allow entry. Else: Access denied.
				if is_authorized:
					self.allow_access(names=names, pin=pin, rfid_uid=rfid_uid)
				else:
					self.deny_access(reason="wrong pin", pin=pin, rfid_uid=rfid_uid)
					is_authenticated = False
			
				# Set reset flag to true
				is_resetting = True

			if is_resetting:

				# Poll for the next RFID and Fingerprint
				fingerprint_thread.is_not_polling = False
				fingerprint_thread.is_found = False
				rfid_thread.is_not_polling = False
				rfid_thread.is_found = False
				is_ask_for_pin = False

				# LED: "Swipe RFID or Finger"
				self.led.clear_display()
				self.led.puts("Swipe RFID\nor Finger")

				# Set flag to false
				is_resetting = False


if __name__ == '__main__':
	SpoonPi().run()
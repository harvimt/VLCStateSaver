#!/usr/bin/env python2
# -*- coding=utf-8 -*- #
from __future__ import unicode_literals, print_function

"""
Copyright © 2012, Mark Harviston <mark.harviston@gmail.com>
This is free software, most forms of redistribution and derivitive works are permitted with the following restrictions.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import dbus, sys, pickle, os, os.path, subprocess, time, datetime
import gobject
from dbus.mainloop.glib import DBusGMainLoop
import urlparse, urllib
import logging
#silence obnoxious error-logging
#possibly not necessary anymore since there should be much fewer errors

dbus_logger = logging.getLogger('dbus.proxies')
dbus_logger.setLevel(logging.CRITICAL)

class FormattableTimeDelta(datetime.timedelta):
	def __format__(self, format_str):
		hours, remainder = divmod(self.duration_time_delta, 3600)
		minutes, seconds = divmod(remainder, 60)

		duration_formatted = '%s:%s:%s' % (hours, minutes, seconds)
		return duration_formatted

DBusGMainLoop(set_as_default=True)
loop = gobject.MainLoop()
bus = dbus.SessionBus(loop)

vlc_prefix = 'org.mpris.MediaPlayer2.vlc-' #vlc bus names should start with this
#not the "default" vlc instance will have the name org.mpris.MediaPlayer2.vlc, as well as org.mpris.MediaPlayer2.vlc-<pid>

def findVLCs():
	global bus
	"""
	return array of dbus vlc names (use get_object to get the actual dbus object)
	"""

	dbus_proxy = bus.get_object ("org.freedesktop.DBus", "/org/freedesktop/DBus")

	return [name for name in dbus_proxy.ListNames() if name.startswith(vlc_prefix)]

def createVLC():
	"""
	create an instance of VLC with dbus enabled and return that VLC's dbus instance
	"""
	print('creating vlc process')

	vlc_proc = subprocess.Popen(('vlc', '-vv'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
	print('vlc proccess created')

	for line in vlc_proc.stdout:
		if 'listening on dbus as: ' in line.decode('utf-8'):
			dbus_name = line.rsplit(': ', 1)[1][:-1]
			print('dbus name found: %s' % dbus_name)
			return dbus_name

	#alternative solution, no gurantee that dbus has started yet though
	#return vlc_prefix + str(vlc_proc.pid)

class VLCStateSave():
	"""
	use findVLCs & createVLCs + dbus interface to save vlc state to a file & reopen it
	"""
	def __init__(self,bus=None):
		self.state_filename = os.path.join(os.environ['HOME'],'.vlc_state')

	def save_state(self, and_quit=False, vlc_data=None):

		if vlc_data is None:
			vlc_data = self.get_state(and_quit)

		with open(self.state_filename,"w") as state_file:
			pickle.dump(vlc_data, state_file)

	def get_state(self, and_quit=False):
		global bus

		vlc_names = findVLCs()
		if len(vlc_names) == 0:
			# if vlc is not running, don't save state, to avoid cronjobs overwriting state
			return

		vlc_names = sorted(vlc_names)
		#print vlc_names
		vlc_data = []
		for  name in vlc_names:
			vlc_app =   dbus.Interface(bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2')
			player =    dbus.Interface(bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.Player')
			tracklist = dbus.Interface(bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.TrackList')
			props =     dbus.Interface(bus.get_object(name, '/org/mpris/MediaPlayer2'), dbus.PROPERTIES_IFACE)

			track_ids = list(props.Get('org.mpris.MediaPlayer2.TrackList', 'Tracks'))
			tracks = tracklist.GetTracksMetadata(track_ids)

			cur_trackid = props.Get('org.mpris.MediaPlayer2.Player', 'Metadata').get('mpris:trackid', None)
			current_pos = props.Get('org.mpris.MediaPlayer2.Player', 'Position')
			current_vol = props.Get('org.mpris.MediaPlayer2.Player', 'Volume')
			current_track = None

			track_uris = []

			for i,track in enumerate(tracks):

				if cur_trackid == track['mpris:trackid']:
					current_track = i

				path = str(track[dbus.String(u'xesam:url')])
				print('added track %s' % path)
				track_uris.append(path)

			vlc_data.append({
				'current_vol' : float(current_vol),
				'current_track': current_track,
				'current_pos': float(current_pos),
				'tracks': track_uris,
			})

			if and_quit: vlc_app.Quit()

		return vlc_data

	def list_state(self, state_info=None):
		if state_info is None:
			with open(self.state_filename,"r") as state_file:
				try:
					state_info = pickle.load(state_file)
				except:
					print ('Failed to load state file')
					return

		#print state_info
		s = \
		'## VLC Instance {instance_num} ##\n'
		'Current Volume: {current_vol} \n'
		'Current Position: {current_pos}µs ({current_pos_td})\n'
		'Tracklist:\n'
		'* = current track'
		for instance_num, vlc_instance_data in enumerate(state_info):

			vlc_instance_data['instance_num'] = instance_num + 1
			vlc_instance_data['current_pos_td'] = datetime.timedelta(milliseconds=vlc_instance_data['current_pos'])

			print(s.format(**vlc_instance_data))

			for track_num, track_url in enumerate(vlc_instance_data['tracks']):
				if track_num == vlc_instance_data['current_track']:
					cur_ind = '*'
				else:
					cur_ind ='-'

				uri_parsed = urlparse.urlparse(track_url)
				if uri_parsed.scheme == 'file':
					print ('%s %s' % (cur_ind, urllib.url2pathname(uri_parsed.path)))
				else:
					print('%s %s' % (cur_ind, track_url))

			print('')
			print('')

	def load_state(self):
		global bus

		"""
		create a VLC instance, then use the dbus interface for that instance to load the playlist and other info into that instance from the statefile
		"""
		with open(self.state_filename,"r") as state_file:
			state_info = pickle.load(state_file)

		for instance_num, vlc_instance_data in enumerate(state_info):
			vlc_name = createVLC()
			print('vlc created, vlc_name=%s' % vlc_name)

			#player = dbus.Interface(bus.get_object(vlc_name, '/Player'), 'org.freedesktop.MediaPlayer')
			#tracklist = dbus.Interface(bus.get_object(vlc_name, '/TrackList'), 'org.freedesktop.MediaPlayer')
			tracklist_iface = 'org.mpris.MediaPlayer2.TrackList'

			vlc_app =   dbus.Interface(bus.get_object(vlc_name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2')
			player =    dbus.Interface(bus.get_object(vlc_name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.Player')
			tracklist = dbus.Interface(bus.get_object(vlc_name, '/org/mpris/MediaPlayer2'), tracklist_iface)
			props =     dbus.Interface(bus.get_object(vlc_name, '/org/mpris/MediaPlayer2'), dbus.PROPERTIES_IFACE)

			prev_id = '/org/mpris/MediaPlayer2/TrackList/NoTrack'
			for i, uri in enumerate(vlc_instance_data['tracks']):
				#print('trying to add uri: %s' % uri)
				tracklist.AddTrack(
					uri,
					prev_id,
					False)

				time.sleep(.1)

				prev_id = props.Get(tracklist_iface,'Tracks')[-1]

				player.Pause()

			if vlc_instance_data['current_track'] is not None:
				player.SetPosition(props.Get(tracklist_iface, 'Tracks')[vlc_instance_data['current_track']], vlc_instance_data['current_pos'])
				time.sleep(.1)
				player.Pause()

if __name__ == "__main__":
	state_saver = VLCStateSave()

	if len(sys.argv) == 1:
		print ('Usage: ' + os.path.basename(sys.argv[0]) + ' <save|save_and_quit|load|list>')
		print ('save: save state to a file')
		print ('save_and_quit: save vlc state to file and quit open instances of vlc after saving')
		print ('load: state from file (creating new vlc instances)')
		print ('list: list contents of the state file')
		print ('list_cur: list the current state w/o saving to file')
	elif sys.argv[1] == 'save':
		state_saver.save_state()
	elif sys.argv[1] == 'save_and_quit':
		state_saver.save_state(and_quit=True)
	elif sys.argv[1] == 'load':
		state_saver.load_state()
	elif sys.argv[1] == 'list':
		state_saver.list_state()
	elif sys.argv[1] == 'list_cur':
		state_saver.list_state(state_saver.get_state())
	else:
		print('bad command line')
		sys.exit(1)
	sys.exit(0)

def repl(name):
	global vlc_app, player, tracklist, props, state_saver
	vlc_app =   dbus.Interface(state_saver.bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2')
	player =    dbus.Interface(state_saver.bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.Player')
	tracklist = dbus.Interface(state_saver.bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.TrackList')
	props =     dbus.Interface(state_saver.bus.get_object(name, '/org/mpris/MediaPlayer2'), dbus.PROPERTIES_IFACE)

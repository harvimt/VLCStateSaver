#! /usr/bin/env python
# load & save VLC state

import dbus, sys, functools, pickle, os, os.path, subprocess, time

from PyQt4.QtCore import *
from PyQt4.QtGui import *
import dbus.mainloop.qt

class VlcFinder (object):
	def __init__ (self, app, action='save_state'):

		self.outstanding = 0
		self.app = app # QApplication instance or glib mainloop instance
		#both support a "quit" method that can be used to kill the app

		self.bus = dbus.SessionBus ()
		self.vlc_names = []

		if action == 'load_state':
			self.pre_load()
		elif action == 'save_state':
			self.pre_save()

	def reply_cb (self, name, ver):
		#print name
		if ver.startswith('vlc '):
			self.vlc_names.append(str(name))
		self.received_result ()

	def error_cb (self, name, msg):
		self.received_result ()

	def received_result (self):
		pass

	def pre_save(self):
		dbus_proxy = self.bus.get_object ("org.freedesktop.DBus", "/org/freedesktop/DBus")
		for name in dbus_proxy.ListNames ():
			if name.startswith (":"):
				try:
					proxy = self.bus.get_object (name, "/")
					iface = dbus.Interface (proxy, "org.freedesktop.MediaPlayer")
				except:
					pass
				iface.Identity (reply_handler = functools.partial (self.reply_cb, name), error_handler = functools.partial (self.error_cb, name))

				self.outstanding += 1

		self.time = QTimer()
		
		self.time.singleShot(1000, self.save_state)

	def save_state(self):
		state_file = open(os.path.join(os.environ['HOME'],'.vlc_state'),"w")
		vlc_data = []
		for  name in self.vlc_names:
			vlc_app = dbus.Interface(self.bus.get_object(name, '/'), 'org.freedesktop.MediaPlayer')
			player = dbus.Interface(self.bus.get_object(name, '/Player'), 'org.freedesktop.MediaPlayer')
			tracklist = dbus.Interface(self.bus.get_object(name, '/TrackList'), 'org.freedesktop.MediaPlayer')
			tracks = []

			current_track = int(tracklist.GetCurrentTrack())
			current_pos = int(player.PositionGet())
			current_vol = int(player.VolumeGet())

			for tracknum in range(0,tracklist.GetLength()):
				trackdata = tracklist.GetMetadata(tracknum)
				path = str(trackdata[dbus.String(u'location')])
				tracks.append(path)

			vlc_data.append({
				'current_vol' : current_vol,
				'current_track': current_track,
				'current_pos': current_pos,
				'tracks': tracks,
			})
			vlc_app.Quit()

		pickle.dump(vlc_data,state_file)
		#self.app.quit ()
		sys.exit(0)

	def pre_load(self):
		state_file = open(os.path.join(os.environ['HOME'],'.vlc_state'),"r")
		self.state_info = pickle.load(state_file)
		vlc_procs = []

		for vlc_data in self.state_info:
			vlc_proc = subprocess.Popen(['/usr/bin/env', 'vlc','--extraintf','oldrc'], stdin=subprocess.PIPE,stderr=subprocess.STDOUT)
			vlc_procs.append(vlc_proc)
			for track in vlc_data['tracks']:
				vlc_proc.stdin.write('enqueue ' + track + '\n');
			time.sleep(1) # give it time for the procs to open
			vlc_proc.stdin.write('volume ' + str(vlc_data['current_vol']*4) + '\n')
			#mpris/dbus format for volume is 0-100 where 0 = 0% and 100=400%
			#rc/command line format is 0-400 where 0 is 0% and 400 is 400%

			time.sleep(1) # give it time for the procs to open
			vlc_proc.stdin.write('goto ' + str(vlc_data['current_track']) + '\n')
			time.sleep(1) # give it time for the procs to open
			vlc_proc.stdin.write('seek ' + str(vlc_data['current_pos']/1000) + '\n')
			time.sleep(1) # give it time for the procs to open
			vlc_proc.stdin.write('pause\n')
		for vlc_proc in vlc_procs:
			retcode = vlc_proc.wait()
			#print 'VLC QUIT return code: ', retcode
		#print 'ALL VLCs quit'

		#self.app.quit()
		#print 'for some reason I\'m still running'
		sys.exit(0)


	#def load_state(self):
		#for name, vlc_data in zip(self.vlc_names, self.state_info):
			vlc_app = dbus.Interface(self.bus.get_object(name, '/'), 'org.freedesktop.MediaPlayer')
			player = dbus.Interface(self.bus.get_object(name, '/Player'), 'org.freedesktop.MediaPlayer')
			tracklist = dbus.Interface(self.bus.get_object(name, '/TrackList'), 'org.freedesktop.MediaPlayer')
			#tracks = vlc_data['tracks']
			#print vlc_data

			#current_track = vlc_data['current_track']
			#current_pos = vlc_data['current_pos']
			#current_vol = vlc_data['current_vol']
			

			#for path in vlc_data['tracks']:
				#print path
				#tracklist.AddTrack(path, False)

			#for track in range(0, current_track + 1):
				#player.Next()

			#TODO disable auto-tabbing for vlc
			#player.VolumeSet(0)
			#player.Play()
			#player.Pause()
			#player.VolumeSet(current_vol)
			#player.PositionSet(current_pos)
			#TODO enable auto-tabbing for vlc
			#TODO tab all VLC windows together

		#self.app.quit ()
	



# coding=utf-8
import dbus, sys, functools, pickle, os, os.path, subprocess, time, datetime, urllib, urlparse
from urllib import url2pathname, pathname2url

import gobject
from dbus.mainloop.glib import DBusGMainLoop
from threading import Thread, Lock
import logging
dbus_logger = logging.getLogger('dbus.proxies')
dbus_logger.setLevel(logging.CRITICAL)

class FormattableTimeDelta(datetime.timedelta):
	def __format__(self, format_str):
		hours, remainder = divmod(duration_time_delta, 3600)
		minutes, seconds = divmod(remainder, 60)

		duration_formatted = '%s:%s:%s' % (hours, minutes, seconds)
		return

class VLCFinder(Thread):
	"""
	helper for findVLCs function
	do not use directly
	"""
	def __init__ (self,*args,**kwargs):
		self.outstanding = 0
		self.loop = None
		self.bus = None
		self.vlc_names = []

		Thread.__init__(self,*args,**kwargs)

	def run(self):
		gobject.threads_init()

		DBusGMainLoop (set_as_default = True)
		self.loop = gobject.MainLoop()
		self.bus = dbus.SessionBus(self.loop)
		self.vlc_names = []

		dbus_proxy = self.bus.get_object ("org.freedesktop.DBus", "/org/freedesktop/DBus")
		for name in dbus_proxy.ListNames():
			if not name.startswith(':'): continue
			#print 'trying %s' % name
			try:
				proxy = self.bus.get_object (name, "/org/mpris/MediaPlayer2")
				iface = dbus.Interface (proxy, dbus.PROPERTIES_IFACE)
			except:
				pass

			try:
				iface.Get ('org.mpris.MediaPlayer2', 'Identity',
						reply_handler = functools.partial (self.reply_cb, name),
						error_handler = functools.partial (self.error_cb, name))
				self.outstanding += 1
			except:
				pass

		self.loop.run()

	def reply_cb (self, name, ver):
		#print('returned %s' % name)
		if ver.lower().startswith('vlc '):
			print('found vlc, %s' % name)
			self.vlc_names.append(str(name))
		self.received_result ()

	def error_cb (self, name, msg):
		self.received_result ()

	def received_result (self):
		if ( self.outstanding == 0):
			self.loop.quit()

def findVLCs():
	"""
	@return array of dbus vlc names (use get_object to get the actual dbus object)

	Problem: there's no way to easily get all dbus instances of one type (say org.mpris.vlc)
	the only way to get all VLCs is to loop through all the names, call Identity() and see what it returns.
	That's all fine and good except a lot of processes flake out and don't respond causing costly timeout

	Solution: send all Identity() requests in parallel with the dbus asynchronous API, then use the python threading api to create a timeout
	"""
	finder_thread = VLCFinder()
	finder_thread.start()
	finder_thread.join(1) #timeout
	finder_thread.loop.quit() #kill the mainloop
	return finder_thread.vlc_names

def createVLC():
	"""
	create an instance of VLC with dbus enabled and return that VLC's dbus instance
	"""
	old_names = set(findVLCs())
	
	print('creating vlc process')
	#vlc_proc = subprocess.Popen(['vlc','--extraintf','dbus'], stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
	#if vlc gets is configured to open dbus, and gets passed --extraintf dbus, it'll create 2 dbus interfaces.
	#yeah coz that makes sense, but that's what it does.

	vlc_proc = subprocess.Popen(['vlc'], stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
	print 'vlc proccess created'
	tries=0
	max_tries=10 #maximum number of seconds to wait

	#wait for VLC to start
	for i in range(5):
		line = vlc_proc.stdout.readline(); #first line will be a Version line
		print line,
		if 'dbus interface: listening on dbus as:':
			#it says which interface it tried to create, not what one actually got created
			break


	#getting this far gurantees VLC has started, but not that all it's modules have been initiliaed
	while True:
		time.sleep(0.5) #wait a little longer for the dbus module to initialize, don't know a better way to do this
		#I've tried -vv & --versbose and waiting for the line to print that says dbus has been initialized, but that doesn't seem to work for somer reason
		#find the new dbus instance by comparing new names to old names

		new_names = set(findVLCs())
		difference = list(new_names - old_names)
		len_diff = len(difference)

		if len_diff > 1:
			print >>sys.stderr,"I'm confused, stop opening extra VLCs, i'm working here!"
			sys.exit(1)
		elif len_diff < 1 and tries < max_tries:
			tries += 1 #try again
		elif len_diff < 1:
			print >>sys.stderr, "VLC instance not created successfully"
			sys.exit(1)
		else:
			break

	return difference[0]

class VLCStateSave():
	"""
	use findVLCs & createVLCs + dbus interface to save vlc state to a file & reopen it
	"""
	def __init__(self,bus=None):
		self.state_filename = os.path.join(os.environ['HOME'],'.vlc_state')
		DBusGMainLoop(set_as_default=True)
		self.bus = dbus.SessionBus()

	def save_state(self, and_quit=False):
		vlc_names = findVLCs()
		if len(vlc_names) == 0:
			# if vlc is not running, don't save state, to avoid cronjobs overwriting state
			return

		vlc_names = sorted(vlc_names)
		#print vlc_names
		state_file = open(self.state_filename,"w")
		vlc_data = []
		for  name in vlc_names:
			vlc_app =   dbus.Interface(self.bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2')
			player =    dbus.Interface(self.bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.Player')
			tracklist = dbus.Interface(self.bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.TrackList')
			props =     dbus.Interface(self.bus.get_object(name, '/org/mpris/MediaPlayer2'), dbus.PROPERTIES_IFACE)

			track_ids = list(props.Get('org.mpris.MediaPlayer2.TrackList', 'Tracks'))
			tracks = tracklist.GetTracksMetadata(track_ids)

			cur_trackid = props.Get('org.mpris.MediaPlayer2.Player', 'Metadata')['mpris:trackid']
			current_pos = props.Get('org.mpris.MediaPlayer2.Player', 'Position')
			current_vol = props.Get('org.mpris.MediaPlayer2.Player', 'Volume')
			current_track = None

			track_uris = []

			for i,track in enumerate(tracks):

				if cur_trackid == track['mpris:trackid']:
					current_track = i

				path = str(track[dbus.String(u'xesam:url')])
				print 'added track %s' % path
				track_uris.append(path)

			vlc_data.append({
				'current_vol' : float(current_vol),
				'current_track': current_track,
				'current_pos': float(current_pos),
				'tracks': track_uris,
			})
			if and_quit: vlc_app.Quit()

		pickle.dump(vlc_data,state_file)
		state_file.close()

	def list_state(self):
		state_file = open(self.state_filename,"r")
		state_info = pickle.load(state_file)
		state_file.close()
		#print state_info
		for instance_num, vlc_instance_data in enumerate(state_info):
			s = \
			u'## VLC Instance {instance_num} ##\n'\
			u'Current Volume: {current_vol} \n'\
			u'Current Position: {current_pos}µs ({current_pos_td})\n'\
			u'Tracklist:\n'\
			u'* = current track'

			vlc_instance_data['instance_num'] = instance_num + 1
			vlc_instance_data['current_pos_td'] = datetime.timedelta(milliseconds=vlc_instance_data['current_pos'])

			print(s.format(**vlc_instance_data))

			for track_num, track_url in enumerate(vlc_instance_data['tracks']):
				if track_num == vlc_instance_data['current_track']:
					cur_ind = '* '
				else:
					cur_ind ='- '
				track_path = track_url
				#track_path = urllib.url2pathname(track_url)
				
				print (cur_ind + track_path)

			print('')
			print('')

	def load_state(self):
		"""
		create a VLC instance, then use the dbus interface for that instance to load the playlist and other info into that instance from the statefile
		"""
		state_file = open(self.state_filename,"r")
		state_info = pickle.load(state_file)
		state_file.close()
		for instance_num, vlc_instance_data in enumerate(state_info):
			vlc_name = createVLC()
			print 'vlc created, vlc_name=%s' % vlc_name

			#player = dbus.Interface(self.bus.get_object(vlc_name, '/Player'), 'org.freedesktop.MediaPlayer')
			#tracklist = dbus.Interface(self.bus.get_object(vlc_name, '/TrackList'), 'org.freedesktop.MediaPlayer')

			vlc_app =   dbus.Interface(self.bus.get_object(vlc_name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2')
			player =    dbus.Interface(self.bus.get_object(vlc_name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.Player')
			tracklist = dbus.Interface(self.bus.get_object(vlc_name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.TrackList')
			props =     dbus.Interface(self.bus.get_object(vlc_name, '/org/mpris/MediaPlayer2'), dbus.PROPERTIES_IFACE)

			for uri in vlc_instance_data['tracks']:
				print 'trying to add uri: %s' % uri
				#path = url2pathname(urlparse.urlparse(uri).path)
				#print 'as file path: %s' % path
				#tracklist.AddTrack( urllib.unquote(urlparse.urlparse(uri)).path, '', False)
				#tracklist.AddTrack( uri, '', False)
				player.OpenUri(uri)
				time.sleep(.1)
				player.Pause()
				time.sleep(.1)

			time.sleep(0.1) #FIXME catch signal instead of sleeping
			#props.Set('org.mpris.MediaPlayer2', 'Volume', str(vlc_instance_data['current_vol']))
			track_ids = props.Get('org.mpris.MediaPlayer2.TrackList', 'Tracks')
			player.SetPosition(track_ids[vlc_instance_data['current_track']], vlc_instance_data['current_pos'])

if __name__ == "__main__":
	state_saver = VLCStateSave()

	if len(sys.argv) == 1:
		print 'Usage: ' + os.path.basename(sys.argv[0]) + ' <save|save_and_quit|load|list>'
		print 'save: save state to a file'
		print 'save_and_quit: save vlc state to file and quit open instances of vlc after saving'
		print 'load: state from file (creating new vlc instances)'
		print 'list: list contents of the state file'
	elif sys.argv[1] == 'save':
		state_saver.save_state()
	elif sys.argv[1] == 'save_and_quit':
		state_saver.save_state(and_quit=True)
	elif sys.argv[1] == 'load':
		state_saver.load_state()
	elif sys.argv[1] == 'list':
		state_saver.list_state()
	else:
		print('wat')

def repl(name):
	global vlc_app, player, tracklist, props, state_saver
	vlc_app =   dbus.Interface(state_saver.bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2')
	player =    dbus.Interface(state_saver.bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.Player')
	tracklist = dbus.Interface(state_saver.bus.get_object(name, '/org/mpris/MediaPlayer2'), 'org.mpris.MediaPlayer2.TrackList')
	props =     dbus.Interface(state_saver.bus.get_object(name, '/org/mpris/MediaPlayer2'), dbus.PROPERTIES_IFACE)

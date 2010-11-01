import dbus, sys, functools, pickle, os, os.path, subprocess, time

import gobject
from dbus.mainloop.glib import DBusGMainLoop
from threading import Thread, Lock

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
			if name.startswith (":"):
				try:
					proxy = self.bus.get_object (name, "/")
					iface = dbus.Interface (proxy, "org.freedesktop.MediaPlayer")
				except:
					pass

				try:
					iface.Identity (reply_handler = functools.partial (self.reply_cb, name), error_handler = functools.partial (self.error_cb, name))
					self.outstanding += 1
				except:
					pass

		self.loop.run()

	def reply_cb (self, name, ver):
		if ver.startswith('vlc '):
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
	old_names = findVLCs()
	vlc_proc = subprocess.Popen(['vlc','--extraintf','dbus'], shell=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)

	#wait for VLC to start
	line = vlc_proc.stdout.readline(); #first line will be a Version line
	#getting this far gurantees VLC has started, but not that all it's modules have been initiliaed
	time.sleep(0.5) #wait a little longer for the dbus module to initialize, don't know a better way to do this
	#I've tried -vv & --versbose and waiting for the line to print that says dbus has been initialized, but that doesn't seem to work for somer reason

	#find the new dbus instance by comparing new names to old names
	new_names = findVLCs()
	difference = list(set(new_names) - set(old_names))
	len_diff = len(difference)

	if len_diff > 1:
		print "I'm confused, stop opening extra VLCs, i'm working here!"
		sys.exit(1)
	elif len_diff < 1:
		print "VLC instance not created successfully"
		sys.exit(1)

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
			if and_quit: vlc_app.Quit()

		pickle.dump(vlc_data,state_file)
		state_file.close()

	def list_state(self):
		state_file = open(self.state_filename,"r")
		state_info = pickle.load(state_file)
		state_file.close()
		#print state_info
		for instance_num, vlc_instance_data in enumerate(state_info):
			print('## VLC Instance ' + str(instance_num+1)+' ##')
			print('Current Volume: ' + str(vlc_instance_data['current_vol']))
			print('Current Position: ' + str(vlc_instance_data['current_pos']))
			print('Tracklist:')
			print('* = current track')
			for track_num, track_path in enumerate(vlc_instance_data['tracks']):
				if track_num == vlc_instance_data['current_track']:
					to_print = '* '
				else:
					to_print='- '
				to_print+=track_path
				print (to_print)

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

			player = dbus.Interface(self.bus.get_object(vlc_name, '/Player'), 'org.freedesktop.MediaPlayer')
			tracklist = dbus.Interface(self.bus.get_object(vlc_name, '/TrackList'), 'org.freedesktop.MediaPlayer')

			for path in vlc_instance_data['tracks']:
				tracklist.AddTrack(path, False)

			player.VolumeSet(0)
			time.sleep(0.1)
			player.Play()
			time.sleep(0.1)
			player.Pause()
			time.sleep(0.1)

			for track in range(0, vlc_instance_data['current_track']):
				player.Next()
				time.sleep(0.1)
				player.Pause()
				time.sleep(0.1)
				time.sleep(0.1)
			player.Pause()

			player.VolumeSet(vlc_instance_data['current_vol'])
			time.sleep(0.1)
			player.PositionSet(vlc_instance_data['current_pos'])
			player.Pause()


if __name__ == "__main__":
	state_saver = VLCStateSave()
	if sys.argv[1] == 'save':
		state_saver.save_state()
	elif sys.argv[1] == 'save_and_quit':
		state_saver.save_state(and_quit=True)
	elif sys.argv[1] == 'load':
		state_saver.load_state()
	elif sys.argv[1] == 'list':
		state_saver.list_state()
	else:
		print 'Usage: ' + sys.argv[0] + ' <save|save_and_quit|load|list>'
		print 'save: save state to a file'
		print 'save_and_quit: save vlc state to file and quit open instances of vlc after saving'
		print 'load: state from file (creating new vlc instances)'
		print 'list: list contents of the state file'
	sys.exit(0)

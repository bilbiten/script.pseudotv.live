#   Copyright (C) 2013 Jason Anderson, Kevin S. Graer
#
#
# This file is part of PseudoTV Live.
#
# PseudoTV is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PseudoTV is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PseudoTV.  If not, see <http://www.gnu.org/licenses/>.

import xbmc, xbmcgui, xbmcaddon, xbmcvfs
import subprocess, os, sys, re
import time, datetime, threading, _strptime
import httplib, urllib, urllib2, feedparser, socket, json
import base64, shutil, random, errno
import Globals, tvdb_api, tmdb_api, xmltv

from urllib import unquote
from urllib import urlopen
from xml.etree import ElementTree as ET
from xml.dom.minidom import parse, parseString
from subprocess import Popen, PIPE, STDOUT
from Playlist import Playlist
from Globals import *
from Channel import Channel
from VideoParser import VideoParser
from FileAccess import FileLock, FileAccess
from sickbeard import *
from couchpotato import *
from tvdb import *
from tmdb import *
from urllib2 import urlopen
from urllib2 import HTTPError, URLError
from datetime import date
from utils import *
from datetime import timedelta

socket.setdefaulttimeout(30)

# Commoncache plugin import
try:
    import StorageServer
except Exception,e:
    import storageserverdummy as StorageServer
       
try:
    from Donor import *
    Donor_Downloaded = True
    xbmc.log("script.pseudotv.live-ChannelList: Donor Imported")
    DonorPath = (os.path.join(ADDON_PATH, 'resources', 'lib', 'Donor.pyo'))
    DL_DonorPath = (os.path.join(ADDON_PATH, 'resources', 'lib', 'Donor.py'))
    if FileAccess.exists(DonorPath):
        if FileAccess.exists(DL_DonorPath):
            try:
                xbmcvfs.delete(xbmc.translatePath(DL_DonorPath))
            except:
                pass             
except:  
    Donor_Downloaded = False
    xbmc.log("script.pseudotv.live-ChannelList: Donor Import Failed, Disabling Donor Features")       
    pass  
   
try:
    from metahandler import metahandlers
except Exception,e:  
    xbmc.log("script.pseudotv.live-ChannelList: metahandler Import Failed" + str(e))    
    pass
      
      
class ChannelList:
    def __init__(self):
        self.networkList = []
        self.studioList = []
        self.mixedGenreList = []
        self.showGenreList = []
        self.movieGenreList = []
        self.musicGenreList = []
        self.showList = []
        self.channels = []
        self.addonFileDetails = []
        self.cached_json_detailed_TV = []
        self.cached_json_detailed_Movie = []
        self.cached_json_detailed_trailers = []  
        self.videoParser = VideoParser()
        self.httpJSON = True
        self.autoplaynextitem = False
        self.sleepTime = 0
        self.discoveredWebServer = False
        self.threadPaused = False
        self.runningActionChannel = 0
        self.runningActionId = 0
        self.enteredChannelCount = 0
        self.background = True
        self.seasonal = False
        random.seed() 

        
    def readConfig(self):
        self.ResetChanLST = list(REAL_SETTINGS.getSetting('ResetChanLST'))
        self.log('Channel Reset List is ' + str(self.ResetChanLST))
        self.channelResetSetting = int(REAL_SETTINGS.getSetting("ChannelResetSetting"))
        self.log('Channel Reset Setting is ' + str(self.channelResetSetting))
        self.forceReset = REAL_SETTINGS.getSetting('ForceChannelReset') == "true"
        self.log('Force Reset is ' + str(self.forceReset))
        self.updateDialog = xbmcgui.DialogProgress()
        self.startMode = int(REAL_SETTINGS.getSetting("StartMode"))
        self.log('Start Mode is ' + str(self.startMode))
        self.backgroundUpdating = int(REAL_SETTINGS.getSetting("ThreadMode"))
        self.incIceLibrary = REAL_SETTINGS.getSetting('IncludeIceLib') == "true"
        self.log("IceLibrary is " + str(self.incIceLibrary))
        self.incBCTs = REAL_SETTINGS.getSetting('IncludeBCTs') == "true"
        self.log("IncludeBCTs is " + str(self.incBCTs))
        self.t = tvdb_api.Tvdb()
        self.tvdbAPI = TVDB(TVDB_API_KEY)
        self.tmdbAPI = TMDB(TMDB_API_KEY)  
        self.sbAPI = SickBeard(REAL_SETTINGS.getSetting('sickbeard.baseurl'),REAL_SETTINGS.getSetting('sickbeard.apikey'))
        self.cpAPI = CouchPotato(REAL_SETTINGS.getSetting('couchpotato.baseurl'),REAL_SETTINGS.getSetting('couchpotato.apikey'))
        self.youtube_ok = self.youtube_player()
        self.log('Youtube Player is ' + str(self.youtube_ok))
        self.playon_ok = self.playon_player()
        self.log('Playon Player is ' + str(self.playon_ok))
        self.findMaxChannels()
        
        if self.forceReset:
            REAL_SETTINGS.setSetting("INTRO_PLAYED","false")
            REAL_SETTINGS.setSetting("ClearLiveArtCache","true")
            REAL_SETTINGS.setSetting('ForceChannelReset', 'false')
            REAL_SETTINGS.setSetting('StartupMessage', 'false')
            self.forceReset = False

        try:
            self.lastResetTime = int(ADDON_SETTINGS.getSetting("LastResetTime"))
        except Exception,e:
            self.lastResetTime = 0

        try:
            self.lastExitTime = int(ADDON_SETTINGS.getSetting("LastExitTime"))
        except Exception,e:
            self.lastExitTime = int(time.time())
            pass
            
            
    def setupList(self):
        self.log("setupList")
        self.readConfig()
        self.updateDialog.create("PseudoTV Live", "Updating channel list")
        self.updateDialog.update(0, "Updating channel list")
        self.updateDialogProgress = 0
        foundvalid = False
        makenewlists = False
        self.background = False
        
        if self.backgroundUpdating > 0 and self.myOverlay.isMaster == True:
            makenewlists = True
            
        # Go through all channels, create their arrays, and setup the new playlist
        for i in range(self.maxChannels):
            self.updateDialogProgress = i * 100 // self.enteredChannelCount
            self.updateDialog.update(self.updateDialogProgress, "Loading channel " + str(i + 1), "waiting for file lock")
            self.channels.append(Channel())
            
            # If the user pressed cancel, stop everything and exit
            if self.updateDialog.iscanceled():
                self.log('Update channels cancelled')
                self.updateDialog.close()
                return None
                
            self.setupChannel(i + 1, self.background, makenewlists, False)
            
            if self.channels[i].isValid:
                foundvalid = True

        if makenewlists == True:
            self.log('makenewlists, Common Cache Purged')
            REAL_SETTINGS.setSetting('ForceChannelReset', 'false')

        if foundvalid == False and makenewlists == False:
            for i in range(self.maxChannels):
                self.updateDialogProgress = i * 100 // self.enteredChannelCount
                self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(i + 1), "waiting for file lock", '')
                self.setupChannel(i + 1, self.background, True, False)

                if self.channels[i].isValid:
                    foundvalid = True
                    break

        self.updateDialog.update(100, "Update complete")
        self.updateDialog.close()
        return self.channels 

        
    def log(self, msg, level = xbmc.LOGDEBUG):
        log('ChannelList: ' + msg, level)

    
    def logDebug(self, msg, level = xbmc.LOGDEBUG):
        if DEBUG == 'true':
            log('ChannelList: ' + msg, level)
            
            
    # Determine the maximum number of channels by opening consecutive
    # playlists until we don't find one
    def findMaxChannels(self):
        self.log('findMaxChannels')
        self.maxChannels = 0
        self.enteredChannelCount = 0

        for i in range(999):
            chtype = 9999
            chsetting1 = ''
            chsetting2 = ''
            chsetting3 = ''
            chsetting4 = ''

            try:
                chtype = int(ADDON_SETTINGS.getSetting('Channel_' + str(i + 1) + '_type'))
                chsetting1 = ADDON_SETTINGS.getSetting('Channel_' + str(i + 1) + '_1')
                chsetting2 = ADDON_SETTINGS.getSetting('Channel_' + str(i + 1) + '_2')
                chsetting3 = ADDON_SETTINGS.getSetting('Channel_' + str(i + 1) + '_3')
                chsetting4 = ADDON_SETTINGS.getSetting('Channel_' + str(i + 1) + '_4')
            except Exception,e:
                pass

            if chtype == 0:
                if FileAccess.exists(xbmc.translatePath(chsetting1)):
                    self.maxChannels = i + 1
                    self.enteredChannelCount += 1
            elif chtype <= 20:
                if len(chsetting1) > 0:
                    self.maxChannels = i + 1
                    self.enteredChannelCount += 1
                    
            if self.forceReset and (chtype != 9999):
                ADDON_SETTINGS.setSetting('Channel_' + str(i + 1) + '_changed', "True")

        self.log('findMaxChannels return ' + str(self.maxChannels))


    def determineWebServer(self):
        if self.discoveredWebServer:
            return

        self.discoveredWebServer = True
        self.webPort = 8080
        self.webUsername = ''
        self.webPassword = ''
        fle = xbmc.translatePath("special://profile/guisettings.xml")

        try:
            xml = FileAccess.open(fle, "r")
        except Exception,e:
            self.log("determineWebServer Unable to open the settings file", xbmc.LOGERROR)
            self.httpJSON = False
            return

        try:
            dom = parse(xml)
        except Exception,e:
            self.log('determineWebServer Unable to parse settings file', xbmc.LOGERROR)
            self.httpJSON = False
            return

        xml.close()
                
        try:
            plname = dom.getElementsByTagName('webserver')
            self.httpJSON = (plname[0].childNodes[0].nodeValue.lower() == 'true')
            self.log('determineWebServer is ' + str(self.httpJSON))
            autoplaynextitem = dom.getElementsByTagName('autoplaynextitem')
            self.autoplaynextitem  = (autoplaynextitem[1].childNodes[0].nodeValue.lower() == 'true')
            self.log('autoplaynextitem is ' + str(self.autoplaynextitem))
            
            if self.httpJSON == True:
                plname = dom.getElementsByTagName('webserverport')
                self.webPort = int(plname[0].childNodes[0].nodeValue)
                self.log('determineWebServer port ' + str(self.webPort))
                plname = dom.getElementsByTagName('webserverusername')
                self.webUsername = plname[0].childNodes[0].nodeValue
                self.log('determineWebServer username ' + self.webUsername)
                plname = dom.getElementsByTagName('webserverpassword')
                self.webPassword = plname[0].childNodes[0].nodeValue
                self.log('determineWebServer password is ' + self.webPassword)
        except Exception,e:
            return

    
    # Code for sending JSON through http adapted from code by sffjunkie (forum.xbmc.org/showthread.php?t=92196)
    def sendJSON(self, command):
        self.log('sendJSON')
        data = ''
        usedhttp = False

        self.determineWebServer()
        self.log('sendJSON command: ' + command)

        # If there have been problems using the server, just skip the attempt and use executejsonrpc
        if self.httpJSON == True:
            try:
                payload = command.encode('utf-8')
            except Exception,e:
                xbmc.log(str(e))
                return data

            headers = {'Content-Type': 'application/json-rpc; charset=utf-8'}

            if self.webUsername != '':
                userpass = base64.encodestring('%s:%s' % (self.webUsername, self.webPassword))[:-1]
                headers['Authorization'] = 'Basic %s' % userpass

            try:
                conn = httplib.HTTPConnection('127.0.0.1', self.webPort)
                conn.request('POST', '/jsonrpc', payload, headers)
                response = conn.getresponse()

                if response.status == 200:
                    data = uni(response.read())
                    usedhttp = True

                conn.close()
            except Exception,e:
                self.log("Exception when getting JSON data")

        if usedhttp == False:
            self.httpJSON = False
            
            try:
                data = xbmc.executeJSONRPC(uni(command))
            except UnicodeEncodeError:
                data = xbmc.executeJSONRPC(ascii(command))

        return uni(data)
        
     
    def setupChannel(self, channel, background = False, makenewlist = False, append = False):
        self.log('setupChannel ' + str(channel))
        returnval = False
        createlist = makenewlist
        chtype = 9999
        chsetting1 = ''
        chsetting2 = ''
        chsetting3 = ''
        chsetting4 = ''
        needsreset = False
        self.background = background
        self.settingChannel = channel

        try:
            chtype = int(ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_type'))
            chsetting1 = ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_1')
            chsetting2 = ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_2')
            chsetting3 = ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_3')
            chsetting4 = ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_4')

        except Exception,e:
            pass

        while len(self.channels) < channel:
            self.channels.append(Channel())

        if chtype == 9999:
            self.channels[channel - 1].isValid = False
            return False

        self.channels[channel - 1].type = chtype
        self.channels[channel - 1].isSetup = True
        self.channels[channel - 1].loadRules(channel)
        self.runActions(RULES_ACTION_START, channel, self.channels[channel - 1])

        try:
            needsreset = ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_changed') == 'True'
            
            # force rebuild
            if chtype == 8:
                self.log("Force LiveTV rebuild")
                needsreset = True
 
            if chtype == 16:
                self.log("Force Playon rebuild")
                needsreset = True

            if needsreset:
                self.channels[channel - 1].isSetup = False
        except Exception,e:
            pass

        # If possible, use an existing playlist
        # Don't do this if we're appending an existing channel
        # Don't load if we need to reset anyway
        if FileAccess.exists(CHANNELS_LOC + 'channel_' + str(channel) + '.m3u') and append == False and needsreset == False:
            try:
                self.channels[channel - 1].totalTimePlayed = int(ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_time', True))
                createlist = True

                if self.background == False:
                    self.updateDialog.update(self.updateDialogProgress, "Loading channel " + str(channel), "reading playlist", '')

                if self.channels[channel - 1].setPlaylist(CHANNELS_LOC + 'channel_' + str(channel) + '.m3u') == True:
                    self.channels[channel - 1].isValid = True
                    self.channels[channel - 1].fileName = CHANNELS_LOC + 'channel_' + str(channel) + '.m3u'
                    returnval = True

                    # If this channel has been watched for longer than it lasts, reset the channel
                    if self.channelResetSetting == 0 and self.channels[channel - 1].totalTimePlayed < self.channels[channel - 1].getTotalDuration():
                        createlist = False

                    if self.channelResetSetting > 0 and self.channelResetSetting < 4:
                        timedif = time.time() - self.lastResetTime

                        if self.channelResetSetting == 1 and timedif < (60 * 60 * 24):
                            createlist = False

                        if self.channelResetSetting == 2 and timedif < (60 * 60 * 24 * 7):
                            createlist = False

                        if self.channelResetSetting == 3 and timedif < (60 * 60 * 24 * 30):
                            createlist = False

                        if timedif < 0:
                            createlist = False

                    if self.channelResetSetting == 4:
                        createlist = False
            except Exception,e:
                pass

        if createlist or needsreset:
            self.channels[channel - 1].isValid = False

            if makenewlist:
                try:#remove old playlist
                    xbmcvfs.delete(CHANNELS_LOC + 'channel_' + str(channel) + '.m3u')
                except Exception,e:
                    pass

                append = False

                if createlist:
                    ADDON_SETTINGS.setSetting('LastResetTime', str(int(time.time())))

        if append == False:
            if chtype == 6 and chsetting2 == str(MODE_ORDERAIRDATE):
                self.channels[channel - 1].mode = MODE_ORDERAIRDATE

            # if there is no start mode in the channel mode flags, set it to the default
            if self.channels[channel - 1].mode & MODE_STARTMODES == 0:
                if self.startMode == 0:
                    self.channels[channel - 1].mode |= MODE_RESUME
                elif self.startMode == 1:
                    self.channels[channel - 1].mode |= MODE_REALTIME
                elif self.startMode == 2:
                    self.channels[channel - 1].mode |= MODE_RANDOM

        if ((createlist or needsreset) and makenewlist) or append:
            if self.background == False:
                self.updateDialogProgress = (channel - 1) * 100 // self.enteredChannelCount
                self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "", '')

            if self.makeChannelList(channel, chtype, chsetting1, chsetting2, chsetting3, chsetting4, append) == True:
                if self.channels[channel - 1].setPlaylist(CHANNELS_LOC + 'channel_' + str(channel) + '.m3u') == True:
                    returnval = True
                    self.channels[channel - 1].fileName = CHANNELS_LOC + 'channel_' + str(channel) + '.m3u'
                    self.channels[channel - 1].isValid = True
                    
                    # Don't reset variables on an appending channel
                    if append == False:
                        self.channels[channel - 1].totalTimePlayed = 0
                        ADDON_SETTINGS.setSetting('Channel_' + str(channel) + '_time', '0')

                        if needsreset:
                            if channel not in self.ResetChanLST:
                                ADDON_SETTINGS.setSetting('Channel_' + str(channel) + '_changed', 'False')
                            REAL_SETTINGS.setSetting('ResetChanLST', '')
                            self.channels[channel - 1].isSetup = True
                    
        self.runActions(RULES_ACTION_BEFORE_CLEAR, channel, self.channels[channel - 1])

        # Don't clear history when appending channels
        if self.background == False and append == False and self.myOverlay.isMaster:
            self.updateDialogProgress = (channel - 1) * 100 // self.enteredChannelCount
            self.updateDialog.update(self.updateDialogProgress, "Loading channel " + str(channel), "clearing history", '')
            self.clearPlaylistHistory(channel)

        if append == False:
            self.runActions(RULES_ACTION_BEFORE_TIME, channel, self.channels[channel - 1])

            if self.channels[channel - 1].mode & MODE_ALWAYSPAUSE > 0:
                self.channels[channel - 1].isPaused = True

            if self.channels[channel - 1].mode & MODE_RANDOM > 0:
                self.channels[channel - 1].showTimeOffset = random.randint(0, self.channels[channel - 1].getTotalDuration())

            if self.channels[channel - 1].mode & MODE_REALTIME > 0:
                timedif = int(self.myOverlay.timeStarted) - self.lastExitTime
                self.channels[channel - 1].totalTimePlayed += timedif

            if self.channels[channel - 1].mode & MODE_RESUME > 0:
                self.channels[channel - 1].showTimeOffset = self.channels[channel - 1].totalTimePlayed
                self.channels[channel - 1].totalTimePlayed = 0

            while self.channels[channel - 1].showTimeOffset > self.channels[channel - 1].getCurrentDuration():
                self.channels[channel - 1].showTimeOffset -= self.channels[channel - 1].getCurrentDuration()
                self.channels[channel - 1].addShowPosition(1)

        self.channels[channel - 1].name = self.getChannelName(chtype, chsetting1)

        if ((createlist or needsreset) and makenewlist) and returnval:
            self.runActions(RULES_ACTION_FINAL_MADE, channel, self.channels[channel - 1])
        else:
            self.runActions(RULES_ACTION_FINAL_LOADED, channel, self.channels[channel - 1])
        
        return returnval

        
    def clearPlaylistHistory(self, channel):
        self.log("clearPlaylistHistory")

        if self.channels[channel - 1].isValid == False:
            self.log("channel not valid, ignoring")
            return

        # if we actually need to clear anything
        if self.channels[channel - 1].totalTimePlayed > (60 * 60 * 24 * 2):
            try:
                fle = FileAccess.open(CHANNELS_LOC + 'channel_' + str(channel) + '.m3u', 'w')
            except Exception,e:
                self.log("clearPlaylistHistory Unable to open the smart playlist", xbmc.LOGERROR)
                return

            flewrite = uni("#EXTM3U\n")
            tottime = 0
            timeremoved = 0

            for i in range(self.channels[channel - 1].Playlist.size()):
                tottime += self.channels[channel - 1].getItemDuration(i)

                if tottime > (self.channels[channel - 1].totalTimePlayed - (60 * 60 * 12)):
                    tmpstr = str(self.channels[channel - 1].getItemDuration(i)) + ','
                    tmpstr += self.channels[channel - 1].getItemTitle(i) + "//" + self.channels[channel - 1].getItemEpisodeTitle(i) + "//" + self.channels[channel - 1].getItemDescription(i) + "//" + self.channels[channel - 1].getItemgenre(i) + "//" + self.channels[channel - 1].getItemtimestamp(i) + "//" + self.channels[channel - 1].getItemLiveID(i)
                    tmpstr = uni(tmpstr[:16384])
                    tmpstr = tmpstr.replace("\\n", " ").replace("\\r", " ").replace("\\\"", "\"")
                    tmpstr = uni(tmpstr) + uni('\n') + uni(self.channels[channel - 1].getItemFilename(i))
                    flewrite += uni("#EXTINF:") + uni(tmpstr) + uni("\n")
                else:
                    timeremoved = tottime

            fle.write(flewrite)
            fle.close()

            if timeremoved > 0:
                if self.channels[channel - 1].setPlaylist(CHANNELS_LOC + 'channel_' + str(channel) + '.m3u') == False:
                    self.channels[channel - 1].isValid = False
                else:
                    self.channels[channel - 1].totalTimePlayed -= timeremoved
                    # Write this now so anything sharing the playlists will get the proper info
                    ADDON_SETTINGS.setSetting('Channel_' + str(channel) + '_time', str(self.channels[channel - 1].totalTimePlayed))


    def getChannelName(self, chtype, setting1):
        self.log('getChannelName ' + str(chtype))
        
        if chtype <= 7 or chtype == 12:
            if len(setting1) == 0:
                return ''

        if chtype == 0:
            return self.getSmartPlaylistName(setting1)
        elif chtype == 1 or chtype == 2 or chtype == 5 or chtype == 6 or chtype == 12:
            return setting1
        elif chtype == 3:
            return setting1 + " TV"
        elif chtype == 4:
            return setting1 + " Movies"
        elif chtype == 12:
            return setting1 + " Music"
        elif chtype == 7:
            if setting1[-1] == '/' or setting1[-1] == '\\':
                return os.path.split(setting1[:-1])[1]
            else:
                return os.path.split(setting1)[1]
        elif chtype == 8:
            return ADDON_SETTINGS.getSetting("Channel_" + str(setting1) + "_opt_1") + " LiveTV"
            
        return ''


    # Open the smart playlist and read the name out of it...this is the channel name
    def getSmartPlaylistName(self, fle):
        self.log('getSmartPlaylistName')
        fle = xbmc.translatePath(fle)

        try:
            xml = FileAccess.open(fle, "r")
        except Exception,e:
            self.log("getSmartPlaylisyName Unable to open the smart playlist " + fle, xbmc.LOGERROR)
            return ''

        try:
            dom = parse(xml)
        except Exception,e:
            self.log('getSmartPlaylistName Problem parsing playlist ' + fle, xbmc.LOGERROR)
            xml.close()
            return ''

        xml.close()

        try:
            plname = dom.getElementsByTagName('name')
            self.log('getSmartPlaylistName return ' + plname[0].childNodes[0].nodeValue)
            return plname[0].childNodes[0].nodeValue
        except Exception,e:
            self.log("Unable to get the playlist name.", xbmc.LOGERROR)
            return ''
    
    
    # Based on a smart playlist, create a normal playlist that can actually be used by us
    def makeChannelList(self, channel, chtype, setting1, setting2, setting3, setting4, append = False):
        self.log('makeChannelList, CHANNEL: ' + str(channel))
        limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
        israndom = False
        reverseOrder = False
        fileListCHK = False
        fileList = []
                      
        #DEFAULT
        if setting4 == '0':
            israndom = False  
            reverseOrder = False
            
        #RANDOM
        elif setting4 == '1':
            israndom = True  
            
        #REVERSE ORDER
        elif setting4 == '2':
            reverseOrder = True
        
        # Directory
        if chtype == 7:
            fileList = self.createDirectoryPlaylist(setting1)
            israndom = True                    
        
        # LiveTV
        elif chtype == 8:
            self.log("Building LiveTV Channel, " + setting1 + " , " + setting2 + " , " + setting3)
            chname = (self.getChannelName(8, channel))
            
            # HDHomeRun #
            if setting2[0:9] == 'hdhomerun' and REAL_SETTINGS.getSetting('HdhomerunMaster') == "true":
                #If you're using a HDHomeRun Dual and want Tuner 1 assign false. *Thanks Blazin912*
                self.log("Building LiveTV using tuner0")
                setting2 = re.sub(r'\d/tuner\d',"0/tuner0",setting2)
            elif setting2[0:9] == 'hdhomerun' and REAL_SETTINGS.getSetting('HdhomerunMaster') == "false":
                self.log("Building LiveTV using tuner1")
                setting2 = re.sub(r'\d/tuner\d',"1/tuner1",setting2)
            
            # Validate Feed #
            fileListCHK = self.Valid_ok(setting2)
            if fileListCHK == True:

                # Validate XMLTV Data #
                if setting3 != '':
                    xmltvValid = self.xmltv_ok(setting1, setting3)
                
                if xmltvValid == True:
                    
                    if setting3 == 'smoothstreams':
                        fileList = self.buildLiveTVFileList(setting1, setting2, setting3, setting4, channel) 
                        if len(fileList) < 24:
                            # Fill Gap Between Listings #
                            fileList = self.fillLiveTVFileList(fileList, chname, channel)                    
                    else:
                        fileList = self.buildLiveTVFileList(setting1, setting2, setting3, setting4, channel)
                        
                    # Fill Empty Listings #
                    if len(fileList) == 0:
                        fileList = self.fillLiveTVFileList(fileList, chname, channel)   
                        ADDON_SETTINGS.setSetting('Channel_' + str(channel) + '_changed', 'True')
                else:
                    fileList = self.fillLiveTVFileList(fileList, chname, channel)   
                    ADDON_SETTINGS.setSetting('Channel_' + str(channel) + '_changed', 'True')
            else:
                self.log('makeChannelList, CHANNEL: ' + str(channel) + ', CHTYPE: ' + str(chtype), 'fileListCHK invalid: ' + str(setting2))
                return
        
        # InternetTV  
        elif chtype == 9:
            self.log("Building InternetTV Channel, " + setting1 + " , " + setting2 + " , " + setting3)
            # Validate Feed #
            fileListCHK = self.Valid_ok(setting2)
            if fileListCHK == True:
                fileList = self.buildInternetTVFileList(setting1, setting2, setting3, setting4, channel)
            else:
                self.log('makeChannelList, CHANNEL: ' + str(channel) + ', CHTYPE: ' + str(chtype), 'fileListCHK invalid: ' + str(setting2))
                return 
                
        # Youtube                          
        elif chtype == 10:
            if self.youtube_ok != False:
                self.log("Building Youtube Channel " + setting1 + " using type " + setting2 + "...")
                
                if setting2 == '31':
                    self.seasonal = True
                    today = datetime.datetime.now()
                    month = today.strftime('%B')
                    if setting1.lower() != month.lower():
                        seasonal.delete("%") 
                        ADDON_SETTINGS.setSetting("Channel_" + str(channel) + "_1", month)
                        
                fileList = self.createYoutubeFilelist(setting1, setting2, setting3, setting4, channel)            
            else:
                self.log('makeChannelList, CHANNEL: ' + str(channel) + ', CHTYPE: ' + str(chtype), 'self.youtube_ok invalid: ' + str(setting2))
                return                 

        # RSS/iTunes/feedburner/Podcast   
        elif chtype == 11:# Validate Feed #
            fileListCHK = self.Valid_ok(setting1)
            if fileListCHK == True:
                self.log("Building RSS Feed " + setting1 + " using type " + setting2 + "...")
                fileList = self.createRSSFileList(setting1, setting2, setting3, setting4, channel)      
            else:
                self.log('makeChannelList, CHANNEL: ' + str(channel) + ', CHTYPE: ' + str(chtype), 'fileListCHK invalid: ' + str(setting2))
                return                   

        # MusicVideos
        elif chtype == 13:
            self.log("Building Music Videos")
            fileList = self.MusicVideos(setting1, setting2, setting3, setting4, channel)
                    
        # Extras
        elif chtype == 14 and Donor_Downloaded == True:
            self.log("Extras, " + setting1 + "...")
            fileList = self.extras(setting1, setting2, setting3, setting4, channel)
            
        # Direct Plugin
        elif chtype == 15:
            # Validate Feed #
            fileListCHK = self.plugin_ok(setting1)
            if fileListCHK == True:
                self.log("Building Plugin Channel, " + setting1 + "...")
                fileList = self.BuildPluginFileList(setting1, setting2, setting3, setting4, channel)            
            else:
                self.log('makeChannelList, CHANNEL: ' + str(channel) + ', CHTYPE: ' + str(chtype), 'fileListCHK invalid: ' + str(setting2))
                return 
        
        # Direct Playon
        elif chtype == 16:
            if self.playon_ok != False:
                self.log("Building Playon Channel, " + setting1 + "...")
                fileList = self.BuildPlayonFileList(setting1, setting2, setting3, setting4, channel)
    
        else:
            if chtype == 0:
                if FileAccess.copy(setting1, MADE_CHAN_LOC + os.path.split(setting1)[1]) == False:
                    if FileAccess.exists(MADE_CHAN_LOC + os.path.split(setting1)[1]) == False:
                        self.log("Unable to copy or find playlist " + setting1)
                        return False

                fle = MADE_CHAN_LOC + os.path.split(setting1)[1]
            else:
                fle = self.makeTypePlaylist(chtype, setting1, setting2)
           
            if len(fle) == 0:
                self.log('Unable to locate the playlist for channel ' + str(channel), xbmc.LOGERROR)
                return False

            try:
                xml = FileAccess.open(fle, "r")
            except Exception,e:
                self.log("makeChannelList Unable to open the smart playlist " + fle, xbmc.LOGERROR)
                return False

            try:
                dom = parse(xml)
            except Exception,e:
                self.log('makeChannelList Problem parsing playlist ' + fle, xbmc.LOGERROR)
                xml.close()
                return False

            xml.close()

            if self.getSmartPlaylistType(dom) == 'mixed':
                if self.incBCTs == True:
                    self.log("makeChannelList, adding CTs to mixed...")
                    PrefileList = self.buildMixedFileList(dom, channel)
                    fileList = self.insertBCTfiles(channel, PrefileList, 'mixed')
                else:
                    fileList = self.buildMixedFileList(dom, channel)

            elif self.getSmartPlaylistType(dom) == 'movies':
                if REAL_SETTINGS.getSetting('Movietrailers') != 'true':
                    self.incBCTs == False
                    
                if self.incBCTs == True:
                    self.log("makeChannelList, adding Trailers to movies...")
                    PrefileList = self.buildFileList(fle, channel, limit, 0)
                    fileList = self.insertBCTfiles(channel, PrefileList, 'movies')
                else:
                    fileList = self.buildFileList(fle, channel, limit, 0)
            
            elif self.getSmartPlaylistType(dom) == 'episodes':
                if self.incBCTs == True:
                    self.log("makeChannelList, adding BCT's to episodes...")
                    PrefileList = self.buildFileList(fle, channel, limit, 0)
                    fileList = self.insertBCTfiles(channel, PrefileList, 'episodes')
                else:
                    fileList = self.buildFileList(fle, channel, limit, 0)
            else:
                fileList = self.buildFileList(fle, channel, limit, 0)

            try:
                order = dom.getElementsByTagName('order')

                if order[0].childNodes[0].nodeValue.lower() == 'random':
                    israndom = True
            except Exception,e:
                pass

        try:
            if append == True:
                channelplaylist = FileAccess.open(CHANNELS_LOC + "channel_" + str(channel) + ".m3u", "r+")
                channelplaylist.seek(0, 2)
            else:
                channelplaylist = FileAccess.open(CHANNELS_LOC + "channel_" + str(channel) + ".m3u", "w")
        except Exception,e:
            self.log('Unable to open the cache file ' + CHANNELS_LOC + 'channel_' + str(channel) + '.m3u', xbmc.LOGERROR)
            return False

        if append == False:
            channelplaylist.write(uni("#EXTM3U\n"))
            #first queue m3u
            
        if fileList != None:  
            if len(fileList) == 0:
                self.log("Unable to get information about channel " + str(channel), xbmc.LOGERROR)
                channelplaylist.close()
                return False

        if israndom:
            random.shuffle(fileList)
            
        if reverseOrder:
            fileList.reverse()

        if len(fileList) > 16384:
            fileList = fileList[:16384]

        fileList = self.runActions(RULES_ACTION_LIST, channel, fileList)
        self.channels[channel - 1].isRandom = israndom

        if append:
            if len(fileList) + self.channels[channel - 1].Playlist.size() > 16384:
                fileList = fileList[:(16384 - self.channels[channel - 1].Playlist.size())]
        else:
            if len(fileList) > 16384:
                fileList = fileList[:16384]

        # Write each entry into the new playlist
        for string in fileList:
            channelplaylist.write(uni("#EXTINF:") + uni(string) + uni("\n"))
            
        channelplaylist.close()
        self.log('makeChannelList return')
        return True

        
    def makeTypePlaylist(self, chtype, setting1, setting2):
    
        if chtype == 1:
            if len(self.networkList) == 0:
                self.fillTVInfo()
            return self.createNetworkPlaylist(setting1)
            
        elif chtype == 2:
            if len(self.studioList) == 0:
                self.fillMovieInfo()
            return self.createStudioPlaylist(setting1)
            
        elif chtype == 3:
            if len(self.showGenreList) == 0:
                self.fillTVInfo()
            return self.createGenrePlaylist('episodes', chtype, setting1)
            
        elif chtype == 4:
            if len(self.movieGenreList) == 0:
                self.fillMovieInfo()
            return self.createGenrePlaylist('movies', chtype, setting1)
            
        elif chtype == 5:
            if len(self.mixedGenreList) == 0:
                if len(self.showGenreList) == 0:
                    self.fillTVInfo()

                if len(self.movieGenreList) == 0:
                    self.fillMovieInfo()

                self.mixedGenreList = self.makeMixedList(self.showGenreList, self.movieGenreList)
                self.mixedGenreList.sort(key=lambda x: x.lower())
            return self.createGenreMixedPlaylist(setting1)
            
        elif chtype == 6:
            if len(self.showList) == 0:
                self.fillTVInfo()
            return self.createShowPlaylist(setting1, setting2)    
            
        elif chtype == 12:
            if len(self.musicGenreList) == 0:
                self.fillMusicInfo()
            return self.createGenrePlaylist('songs', chtype, setting1)

        self.log('makeTypePlaylists invalid channel type: ' + str(chtype))
        return ''    
    
    
    def createNetworkPlaylist(self, network):
        flename = xbmc.makeLegalFilename(GEN_CHAN_LOC + 'network_' + network + '.xsp')
        
        try:
            fle = FileAccess.open(flename, "w")
        except Exception,e:
            self.Error('Unable to open the cache file ' + flename, xbmc.LOGERROR)
            return ''

        self.writeXSPHeader(fle, "episodes", self.getChannelName(1, network))
        network = network.lower()
        added = False

        fle.write('    <rule field="tvshow" operator="is">\n')
        
        for i in range(len(self.showList)):
            if self.threadPause() == False:
                fle.close()
                return ''

            if self.showList[i][1].lower() == network:
                theshow = self.cleanString(self.showList[i][0])                
                fle.write('        <value>' + theshow + '</value>\n')            
                added = True
        
        fle.write('    </rule>\n')
        
        self.writeXSPFooter(fle, 0, "random")
        fle.close()

        if added == False:
            return ''
        return flename


    def createShowPlaylist(self, show, setting2):
        order = 'random'

        try:
            setting = int(setting2)

            if setting & MODE_ORDERAIRDATE > 0:
                order = 'episode'
        except Exception,e:
            pass

        flename = xbmc.makeLegalFilename(GEN_CHAN_LOC + 'Show_' + show + '_' + order + '.xsp')

        try:
            fle = FileAccess.open(flename, "w")
        except Exception,e:
            self.Error('Unable to open the cache file ' + flename, xbmc.LOGERROR)
            return ''

        self.writeXSPHeader(fle, 'episodes', self.getChannelName(6, show))
        show = self.cleanString(show)
        fle.write('    <rule field="tvshow" operator="is">\n')
        fle.write('        <value>' + show + '</value>\n')
        fle.write('    </rule>\n')
        
        self.writeXSPFooter(fle, 0, order)
        fle.close()
        return flename

    
    def fillMixedGenreInfo(self):
        if len(self.mixedGenreList) == 0:
            if len(self.showGenreList) == 0:
                self.fillTVInfo()
            if len(self.movieGenreList) == 0:
                self.fillMovieInfo()

            self.mixedGenreList = self.makeMixedList(self.showGenreList, self.movieGenreList)
            self.mixedGenreList.sort(key=lambda x: x.lower())

    
    def makeMixedList(self, list1, list2):
        self.log("makeMixedList")
        newlist = []

        for item in list1:
            curitem = item.lower()

            for a in list2:
                if curitem == a.lower():
                    newlist.append(item)
                    break
        return newlist
    
    
    def createGenreMixedPlaylist(self, genre):
        flename = xbmc.makeLegalFilename(GEN_CHAN_LOC + 'mixed_' + genre + '.xsp')

        try:
            fle = FileAccess.open(flename, "w")
        except Exception,e:
            self.Error('Unable to open the cache file ' + flename, xbmc.LOGERROR)
            return ''

        epname = os.path.basename(self.createGenrePlaylist('episodes', 3, genre))
        moname = os.path.basename(self.createGenrePlaylist('movies', 4, genre))
        self.writeXSPHeader(fle, 'mixed', self.getChannelName(5, genre))
        fle.write('    <rule field="playlist" operator="is">' + epname + '</rule>\n')
        fle.write('    <rule field="playlist" operator="is">' + moname + '</rule>\n')
        self.writeXSPFooter(fle, 0, "random")
        fle.close()
        return flename


    def createGenrePlaylist(self, pltype, chtype, genre):
        flename = xbmc.makeLegalFilename(GEN_CHAN_LOC + pltype + '_' + genre + '.xsp')

        try:
            fle = FileAccess.open(flename, "w")
        except Exception,e:
            self.Error('Unable to open the cache file ' + flename, xbmc.LOGERROR)
            return ''

        self.writeXSPHeader(fle, pltype, self.getChannelName(chtype, genre))
        genre = self.cleanString(genre)
        fle.write('    <rule field="genre" operator="is">\n')
        fle.write('        <value>' + genre + '</value>\n')
        fle.write('    </rule>\n')
        
        self.writeXSPFooter(fle, 0, "random")
        fle.close()
        return flename


    def createStudioPlaylist(self, studio):
        flename = xbmc.makeLegalFilename(GEN_CHAN_LOC + 'Studio_' + studio + '.xsp')

        try:
            fle = FileAccess.open(flename, "w")
        except Exception,e:
            self.Error('Unable to open the cache file ' + flename, xbmc.LOGERROR)
            return ''

        self.writeXSPHeader(fle, "movies", self.getChannelName(2, studio))
        studio = self.cleanString(studio)
        fle.write('    <rule field="studio" operator="is">\n')
        fle.write('        <value>' + studio + '</value>\n')
        fle.write('    </rule>\n')
        
        self.writeXSPFooter(fle, 0, "random")
        fle.close()
        return flename
        
        
    def createCinemaExperiencePlaylist(self):
        flename = xbmc.makeLegalFilename(GEN_CHAN_LOC + 'movies_CinemaExperience.xsp')
        twoyearsold = date.today().year - 2
        limit = 25
            
        try:
            fle = FileAccess.open(flename, "w")
        except Exception,e:
            self.Error('Unable to open the cache file ' + flename, xbmc.LOGERROR)
            return ''

        fle.write('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n')
        fle.write('<smartplaylist type="movies">\n')
        fle.write('    <name>Cinema Experience</name>\n')
        fle.write('    <match>all</match>\n')
        fle.write('    <rule field="videoresolution" operator="greaterthan">\n')
        fle.write('        <value>720</value>\n')
        fle.write('    </rule>\n')
        fle.write('    <rule field="playcount" operator="is">\n')
        fle.write('        <value>0</value>\n')
        fle.write('    </rule>\n')
        fle.write('    <rule field="year" operator="greaterthan">\n')
        fle.write('        <value>' + str(twoyearsold) + '</value>\n')
        fle.write('    </rule>\n')
        fle.write('    <group>none</group>\n')
        fle.write('    <limit>'+str(limit)+'</limit>\n')
        fle.write('    <order direction="ascending">random</order>\n')
        fle.write('</smartplaylist>\n')
        fle.close()
        return flename
        
        
    def createRecentlyAddedTV(self):
        flename = xbmc.makeLegalFilename(GEN_CHAN_LOC + 'episodes_RecentlyAddedTV.xsp')
        limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
            
        try:
            fle = FileAccess.open(flename, "w")
        except Exception,e:
            self.Error('Unable to open the cache file ' + flename, xbmc.LOGERROR)
            return ''

        fle.write('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n')
        fle.write('<smartplaylist type="episodes">\n')
        fle.write('    <name>Recently Added TV</name>\n')
        fle.write('    <match>all</match>\n')
        fle.write('    <rule field="dateadded" operator="inthelast">\n')
        fle.write('        <value>14</value>\n')
        fle.write('    </rule>\n')
        fle.write('    <limit>'+str(limit)+'</limit>\n')
        fle.write('    <order direction="descending">dateadded</order>\n')
        fle.write('</smartplaylist>\n')
        fle.close()
        return flename
        
    
    def createRecentlyAddedMovies(self):
        flename = xbmc.makeLegalFilename(GEN_CHAN_LOC + 'movies_RecentlyAddedMovies.xsp')
        limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
            
        try:
            fle = FileAccess.open(flename, "w")
        except Exception,e:
            self.Error('Unable to open the cache file ' + flename, xbmc.LOGERROR)
            return ''

        fle.write('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n')
        fle.write('<smartplaylist type="movies">\n')
        fle.write('    <name>Recently Added Movies</name>\n')
        fle.write('    <match>all</match>\n')
        fle.write('    <rule field="dateadded" operator="inthelast">\n')
        fle.write('        <value>14</value>\n')
        fle.write('    </rule>\n')
        fle.write('    <limit>'+str(limit)+'</limit>\n')
        fle.write('    <order direction="descending">dateadded</order>\n')
        fle.write('</smartplaylist>\n')
        fle.close()
        return flename


    def createDirectoryPlaylist(self, setting1):
        self.log("createDirectoryPlaylist " + setting1)
        fileList = []
        LocalLST = []
        LocalFLE = ''
        filecount = 0 
        LiveID = 'tvshow|0|0|False|1|NR|'
        LocalLST = self.walk(setting1)

        if self.background == False:
            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Videos", "getting file list")
        
        for f in LocalLST:         
            if self.threadPause() == False:
                del fileList[:]
                break
                
        for i in range(len(LocalLST)):    
            LocalFLE = LocalLST[i]
            duration = self.videoParser.getVideoLength(LocalFLE)
                                            
            if duration == 0 and LocalFLE[-4:].lower() == 'strm':
                duration = 3600
                self.log("createDirectoryPlaylist, no strm duration found defaulting to 3600")
                    
            if duration > 0:
                filecount += 1
                
                if self.background == False:
                    if filecount == 1:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Videos", "added " + str(filecount) + " entry")
                    else:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Videos", "added " + str(filecount) + " entries")
                
                title = (os.path.split(LocalFLE)[1])
                title = os.path.splitext(title)[0].replace('.', ' ')
                description = LocalFLE.replace('//','/').replace('/','\\')
                
                tmpstr = str(duration) + ',' + title + "//" + 'Directory' + "//" + description + "//" + 'Unknown' + "////" + LiveID + '\n' + (LocalFLE)
                tmpstr = uni(tmpstr[:16384])
                fileList.append(tmpstr)
                
        if filecount == 0:
            self.log('Unable to access Videos files in ' + setting1)
        return fileList


    def writeXSPHeader(self, fle, pltype, plname):
        fle.write('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n')
        fle.write('<smartplaylist type="'+pltype+'">\n')
        plname = self.cleanString(plname)
        fle.write('    <name>'+plname+'</name>\n')
        fle.write('    <match>one</match>\n')


    def writeXSPFooter(self, fle, limit, order):
        limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
        self.log('limit = ' + str(limit))  
            
        if limit > 0:
            fle.write('    <limit>'+str(limit)+'</limit>\n')

        fle.write('    <order direction="ascending">' + order + '</order>\n')
        fle.write('</smartplaylist>\n')

    
    def cleanString(self, string):
        newstr = uni(string)
        newstr = newstr.replace('&', '&amp;')
        newstr = newstr.replace('>', '&gt;')
        newstr = newstr.replace('<', '&lt;')
        return uni(newstr)

    
    def uncleanString(self, string):
        self.log("uncleanString")
        newstr = string
        newstr = newstr.replace('&amp;', '&')
        newstr = newstr.replace('&gt;', '>')
        newstr = newstr.replace('&lt;', '<')
        return uni(newstr)
               
            
    def fillMusicInfo(self, sortbycount = False):
        self.log("fillMusicInfo")
        self.musicGenreList = []
        json_query = ('{"jsonrpc": "2.0", "method": "AudioLibrary.GetAlbums", "params": {"properties":["genre"]}, "id": 1}')
        
        if self.background == False:
            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding music", "reading music data")

        json_folder_detail = self.sendJSON(json_query)
        detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)

        for f in detail:
            if self.threadPause() == False:
                del self.musicGenreList[:]
                return

            match = re.search('"genre" *: *\[(.*?)\]', f)
          
            if match:
                genres = match.group(1).split(',')
               
                for genre in genres:
                    found = False
                    curgenre = genre.lower().strip('"').strip()

                    for g in range(len(self.musicGenreList)):
                        if self.threadPause() == False:
                            del self.musicGenreList[:]
                            return
                            
                        itm = self.musicGenreList[g]

                        if sortbycount:
                            itm = itm[0]

                        if curgenre == itm.lower():
                            found = True

                            if sortbycount:
                                self.musicGenreList[g][1] += 1

                            break

                    if found == False:
                        if sortbycount:
                            self.musicGenreList.append([genre.strip('"').strip(), 1])
                        else:
                            self.musicGenreList.append(genre.strip('"').strip())
    
        if sortbycount:
            self.musicGenreList.sort(key=lambda x: x[1], reverse = True)
        else:
            self.musicGenreList.sort(key=lambda x: x.lower())

        if (len(self.musicGenreList) == 0):
            self.logDebug(json_folder_detail)

        self.log("found genres " + str(self.musicGenreList))
     
    
    def fillTVInfo(self, sortbycount = False):
        self.log("fillTVInfo")
        json_query = ('{"jsonrpc": "2.0", "method": "VideoLibrary.GetTVShows", "params": {"properties":["studio", "genre"]}, "id": 1}')

        if self.background == False:
            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Videos", "reading TV data")

        json_folder_detail = self.sendJSON(json_query)
        detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)

        for f in detail:
            if self.threadPause() == False:
                del self.networkList[:]
                del self.showList[:]
                del self.showGenreList[:]
                return

            match = re.search('"studio" *: *\[(.*?)\]', f)
            network = ''

            if match:
                network = (match.group(1).split(','))[0]
                network = network.strip('"').strip()
                found = False

                for item in range(len(self.networkList)):
                    if self.threadPause() == False:
                        del self.networkList[:]
                        del self.showList[:]
                        del self.showGenreList[:]
                        return

                    itm = self.networkList[item]

                    if sortbycount:
                        itm = itm[0]

                    if itm.lower() == network.lower():
                        found = True

                        if sortbycount:
                            self.networkList[item][1] += 1

                        break

                if found == False and len(network) > 0:
                    if sortbycount:
                        self.networkList.append([network, 1])
                    else:
                        self.networkList.append(network)

            match = re.search('"label" *: *"(.*?)",', f)

            if match:
                show = match.group(1).strip()
                self.showList.append([show, network])
                
            match = re.search('"genre" *: *\[(.*?)\]', f)

            if match:
                genres = match.group(1).split(',')
                
                for genre in genres:
                    found = False
                    curgenre = genre.lower().strip('"').strip()

                    for g in range(len(self.showGenreList)):
                        if self.threadPause() == False:
                            del self.networkList[:]
                            del self.showList[:]
                            del self.showGenreList[:]
                            return

                        itm = self.showGenreList[g]

                        if sortbycount:
                            itm = itm[0]

                        if curgenre == itm.lower():
                            found = True

                            if sortbycount:
                                self.showGenreList[g][1] += 1

                            break

                    if found == False:
                        if sortbycount:
                            self.showGenreList.append([genre.strip('"').strip(), 1])
                        else:
                            self.showGenreList.append(genre.strip('"').strip())

        if sortbycount:
            self.networkList.sort(key=lambda x: x[1], reverse = True)
            self.showGenreList.sort(key=lambda x: x[1], reverse = True)
        else:
            self.networkList.sort(key=lambda x: x.lower())
            self.showGenreList.sort(key=lambda x: x.lower())

        if (len(self.showList) == 0) and (len(self.showGenreList) == 0) and (len(self.networkList) == 0):
            self.logDebug(json_folder_detail)

        self.log("found shows " + str(self.showList))
        self.log("found genres " + str(self.showGenreList))
        self.log("fillTVInfo return " + str(self.networkList))


    def fillMovieInfo(self, sortbycount = False):
        self.log("fillMovieInfo")
        studioList = []
        json_query = ('{"jsonrpc": "2.0", "method": "VideoLibrary.GetMovies", "params": {"properties":["studio", "genre"]}, "id": 1}')

        if self.background == False:
            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Videos", "reading movie data")

        json_folder_detail = self.sendJSON(json_query)
        detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)

        for f in detail:
            if self.threadPause() == False:
                del self.movieGenreList[:]
                del self.studioList[:]
                del studioList[:]
                break

            match = re.search('"genre" *: *\[(.*?)\]', f)

            if match:
                genres = match.group(1).split(',')

                for genre in genres:
                    found = False
                    curgenre = genre.lower().strip('"').strip()

                    for g in range(len(self.movieGenreList)):
                        itm = self.movieGenreList[g]

                        if sortbycount:
                            itm = itm[0]

                        if curgenre == itm.lower():
                            found = True

                            if sortbycount:
                                self.movieGenreList[g][1] += 1

                            break

                    if found == False:
                        if sortbycount:
                            self.movieGenreList.append([genre.strip('"').strip(), 1])
                        else:
                            self.movieGenreList.append(genre.strip('"').strip())

            match = re.search('"studio" *: *\[(.*?)\]', f)
           
            if match:
                studios = match.group(1).split(',')
                
                for studio in studios:
                    curstudio = studio.strip('"').strip()
                    found = False

                    for i in range(len(studioList)):
                        if studioList[i][0].lower() == curstudio.lower():
                            studioList[i][1] += 1
                            found = True
                            break

                    if found == False and len(curstudio) > 0:
                        studioList.append([curstudio, 1])

        maxcount = 0

        for i in range(len(studioList)):
            if studioList[i][1] > maxcount:
                maxcount = studioList[i][1]

        bestmatch = 1
        lastmatch = 1000
        counteditems = 0

        for i in range(maxcount, 0, -1):
            itemcount = 0

            for j in range(len(studioList)):
                if studioList[j][1] == i:
                    itemcount += 1

            if abs(itemcount + counteditems - 8) < abs(lastmatch - 8):
                bestmatch = i
                lastmatch = itemcount

            counteditems += itemcount

        if sortbycount:
            studioList.sort(key=lambda x: x[1], reverse=True)
            self.movieGenreList.sort(key=lambda x: x[1], reverse=True)
        else:
            studioList.sort(key=lambda x: x[0].lower())
            self.movieGenreList.sort(key=lambda x: x.lower())

        for i in range(len(studioList)):
            if studioList[i][1] >= bestmatch:
                if sortbycount:
                    self.studioList.append([studioList[i][0], studioList[i][1]])
                else:
                    self.studioList.append(studioList[i][0])

        if (len(self.movieGenreList) == 0) and (len(self.studioList) == 0):
            self.logDebug(json_folder_detail)

        self.log("found genres " + str(self.movieGenreList))
        self.log("fillMovieInfo return " + str(self.studioList))


    def makeMixedList(self, list1, list2):
        self.log("makeMixedList")
        newlist = []

        for item in list1:
            curitem = item.lower()

            for a in list2:
                if curitem == a.lower():
                    newlist.append(item)
                    break

        self.log("makeMixedList return " + str(newlist))
        return newlist
        
        
    def packGenreLiveID(self, GenreLiveID):
        self.log("packGenreLiveID")
        genre = GenreLiveID[0]
        GenreLiveID.pop(0)
        LiveID = (str(GenreLiveID)).replace("u'",'').replace(',','|').replace('[','').replace(']','').replace("'",'').replace(" ",'') + '|'
        return genre, LiveID
        
        
    def unpackLiveID(self, LiveID):
        self.log("unpackLiveID")
        LiveID = LiveID.split('|')
        return LiveID
    
         
    def buildGenreLiveID(self, showtitle, type):
        self.log("buildGenreLiveID")        
        #############################################
        #Genre|TYPE|ID|DBID|MANAGED|PLAYCOUNT|RATING#
        #############################################
        title = ''
        year = ''
        Managed = False
        imdbnumber = 0
        dbid = 0
        playcount = 1
        genre = 'Unknown'
        rating = 'NR'
        file_detail = []
        GenreLiveID = ['Unknown','tvshow',0,0,False,1,'NR']

        try:
            if type == 'tvshow':
                if not self.cached_json_detailed_TV:
                    self.log("buildGenreLiveID, tvshow; json_detail storing in memory")
                    json_query = ('{"jsonrpc":"2.0","method":"VideoLibrary.GetTVShows","params":{"properties":["title","year","genre","mpaa","imdbnumber","playcount"]}, "id": 1}')
                    self.cached_json_detailed_TV = self.sendJSON(json_query)
                    json_detail = self.cached_json_detailed_TV
                else:
                    json_detail = self.cached_json_detailed_TV
                    self.log("buildGenreLiveID, tvshow; json_detail using memory")
            else:
                if not self.cached_json_detailed_Movie:
                    self.log("buildGenreLiveID, movie; json_detail storing in memory")
                    json_query = ('{"jsonrpc":"2.0","method":"VideoLibrary.GetMovies","params":{"properties":["title","year","genre","mpaa","imdbnumber","playcount"]}, "id": 1}')
                    self.cached_json_detailed_Movie = self.sendJSON(json_query)
                    json_detail = self.cached_json_detailed_Movie
                else:
                    json_detail = self.cached_json_detailed_Movie
                    self.log("buildGenreLiveID, movie; json_detail using memory")

            file_detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_detail)

            for f in file_detail:
                if self.threadPause() == False:
                    del fileList[:]
                    break
                
            for f in (file_detail):
                #run through each result in json return
                titles = re.search('"title" *: *"(.*?)"', f)
               
                if titles:
                    showtitle = showtitle.replace(', ','').replace('_','').replace('*','').replace(',',' ').replace('/','').replace('()',' ').replace('( )','').replace('\\','')      
                    title = (titles.group(1)).replace(', ','').replace('_','').replace('*','').replace(',',' ').replace('/','').replace('()',' ').replace('( )','').replace('\\','')
                                        
                    if title.lower() == showtitle.lower():
                        years = re.search('"year" *: *([0-9]*?) *(.*?)', f)
                        genres = re.search('"genre" *: *\[(.*?)\]', f)
                        playcounts = re.search('"playcount" *: *([0-9]*?),', f)
                        imdbnumbers = re.search('"imdbnumber" *: *"(.*?)"', f)
                        ratings = re.search('"mpaa" *: *"(.*?)"', f)

                        if type == 'tvshow':
                            dbids = re.search('"tvshowid" *: *([0-9]*?),', f)    
                            
                        else:
                            dbids = re.search('"movieid" *: *([0-9]*?),', f)
                            
                        if not years:
                            try:
                                year = ((title.split(' ('))[1]).replace(')','')
                            except Exception,e:
                                try:
                                    year = ((showtitle.split(' ('))[1]).replace(')','')
                                except:
                                    year = ''
                                    pass
                                
                        if genres:
                            genre = (genres.group(1).split(',')[0]).replace('"','')                            
                        
                        if playcounts:
                            playcount = playcounts.group(1)

                        if ratings:
                            rating = self.cleanRating(ratings.group(1))
                            if type == 'movie':
                                rating = rating.replace('TV-','')
                                rating = rating[0:5]
                                try:
                                    rating = rating.split(' ')[0]
                                except:
                                    pass
                        
                        if imdbnumbers:
                            imdbnumber = imdbnumbers.group(1)
                            
                        if dbids:
                            dbid = dbids.group(1)
                            
                        break
            
            if REAL_SETTINGS.getSetting('EnhancedGuideData') == 'true':    
            
                if not imdbnumber or imdbnumber == 0:
                    if type == 'tvshow':
                        imdbnumber = self.getTVDBID(showtitle, year)
                    else:
                        imdbnumber = self.getIMDBIDmovie(showtitle, year)

                if not genre or genre == 'Unknown':
                    genre = (self.getGenre(type, showtitle, year))

                if not rating or rating == 'NR':
                    rating = (self.getRating(type, showtitle, year, imdbnumber))

                if imdbnumber != 0:
                    if type == 'tvshow':
                        Managed = self.sbManaged(imdbnumber)
                    else:
                        Managed = self.cpManaged(showtitle, imdbnumber)
                    
            GenreLiveID = [genre, type, imdbnumber, dbid, Managed, playcount, rating]

        except Exception,e:
            pass

        return GenreLiveID
        
        
    def buildFileList(self, dir_name, channel, limit, sort):
        xbmc.log("buildFileList Cache")
        if Cache_Enabled == True and SETTOP == False:
            try:
                result = localTV.cacheFunction(self.buildFileList_NEW, dir_name, channel, limit, sort)
            except:
                result = self.buildFileList_NEW(dir_name, channel, limit, sort)
                pass
        else:
            result = self.buildFileList_NEW(dir_name, channel, limit, sort)
        if not result:
            result = []
        return result  
        

    def buildFileList_NEW(self, dir_name, channel, limit, sort): ##fix music channel todo
        self.log("buildFileList_NEW")
        FleType = 'video'
        fileList = []
        seasoneplist = []
        filecount = 0
        LiveID = 'tvshow|0|0|False|1|NR|'
        Managed = False
        file_detail = []
        json_query = uni('{"jsonrpc": "2.0", "method": "Files.GetDirectory", "params": {"directory": "%s", "media": "%s", "properties":["title","year","mpaa","imdbnumber","description","season","episode","playcount","genre","duration","runtime","showtitle","album","artist","plot","plotoutline","tagline"]}, "id": 1}' % (self.escapeDirJSON(dir_name), FleType))

        if self.background == False:
            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Videos", "querying database")
        
        json_folder_detail = self.sendJSON(json_query)
        file_detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)

        for f in file_detail:
            if self.threadPause() == False:
                del fileList[:]
                break
                
            match = re.search('"file" *: *"(.*?)",', f)
            istvshow = False

            if match:
                if(match.group(1).endswith("/") or match.group(1).endswith("\\")):
                    fileList.extend(self.buildFileList(match.group(1), channel, limit, 0))
                else:
                    f = self.runActions(RULES_ACTION_JSON, channel, f)
                    duration = re.search('"duration" *: *([0-9]*?),', f)
                    
                    # If music duration returned, else 0
                    try:
                        dur = int(duration.group(1))
                    except Exception,e:
                        dur = 0
                                
                    # If duration doesn't exist, try to figure it out
                    if dur == 0:
                        try:
                            dur = self.videoParser.getVideoLength(uni(match.group(1)).replace("\\\\", "\\"))
                        except Exception,e:
                            dur = 0
                            
                    # As a last resort (since it's not as accurate), use runtime
                    if dur == 0:
                        duration = re.search('"runtime" *: *([0-9]*?),', f)
                        try:
                            dur = int(duration.group(1))
                        except Exception,e:
                            dur = 0

                    self.log("buildFileList.dur = " + str(dur))
                   
                    # Remove any file types that we don't want (ex. IceLibrary, ie. Strms)
                    if self.incIceLibrary == False:
                        if match.group(1).replace("\\\\", "\\")[-4:].lower() == 'strm':
                            dur = 0
                    else:
                        if dur == 0 and match.group(1).replace("\\\\", "\\")[-4:].lower() == 'strm':
                            dur = 3600      
                    try:
                        if dur > 0:
                            filecount += 1
                            seasonval = -1
                            epval = -1

                            if self.background == False:
                                if filecount == 1:
                                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Videos", "added " + str(filecount) + " entry")
                                else:
                                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Videos", "added " + str(filecount) + " entries")
                            
                            tmpstr = str(dur) + ','
                            titles = re.search('"label" *: *"(.*?)"', f)
                            showtitles = re.search('"showtitle" *: *"(.*?)"', f)
                            plots = re.search('"plot" *: *"(.*?)",', f)
                            plotoutlines = re.search('"plotoutline" *: *"(.*?)",', f)
                            years = re.search('"year" *: *([0-9]*?)', f)
                            genres = re.search('"genre" *: *\[(.*?)\]', f)
                            playcounts = re.search('"playcount" *: *([0-9]*?),', f)
                            imdbnumbers = re.search('"imdbnumber" *: *"(.*?)"', f)
                            ratings = re.search('"mpaa" *: *"(.*?)"', f)
                            descriptions = re.search('"description" *: *"(.*?)"', f)
                            
                            if showtitles != None and len(showtitles.group(1)) > 0:
                                type = 'tvshow'
                                dbids = re.search('"tvshowid" *: *([0-9]*?),', f)    
                            else:
                                type = 'movie'
                                dbids = re.search('"movieid" *: *([0-9]*?),', f)
                            
                            if years == None and len(years.group(1)) == 0:
                                try:
                                    year = int(((showtitles.group(1)).split(' ('))[1].replace(')',''))
                                except Exception,e:
                                    try:
                                        year = int(((titles.group(1)).split(' ('))[1].replace(')',''))
                                    except:
                                        year = 0
                                        pass
                            else:
                                year = 0
                                
                            if genres != None and len(genres.group(1)) > 0:
                                genre = ((genres.group(1).split(',')[0]).replace('"',''))
                            else:
                                genre = 'Unknown'
                            
                            if playcounts != None and len(playcounts.group(1)) > 0:
                                playcount = playcounts.group(1)
                            else:
                                playcount = 1
                    
                            if ratings != None and len(ratings.group(1)) > 0:
                                rating = self.cleanRating(ratings.group(1))
                                if type == 'movie':
                                    rating = rating[0:5]
                                    try:
                                        rating = rating.split(' ')[0]
                                    except:
                                        pass
                            else:
                                rating = 'NR'
                            
                            if imdbnumbers != None and len(imdbnumbers.group(1)) > 0:
                                imdbnumber = imdbnumbers.group(1)
                            else:
                                imdbnumber = 0
                                
                            if dbids != None and len(dbids.group(1)) > 0:
                                dbid = dbids.group(1)
                            else:
                                dbid = 0

                            if plots != None and len(plots.group(1)) > 0:
                                theplot = (plots.group(1)).replace('\\','').replace('\n','')
                            elif descriptions != None and len(descriptions.group(1)) > 0:
                                theplot = (descriptions.group(1)).replace('\\','').replace('\n','')
                            else:
                                theplot = (titles.group(1)).replace('\\','').replace('\n','')
                            
                            try:
                                theplot = (self.trim(theplot, 350, '...'))
                            except Exception,e:
                                self.log("Plot Trim failed" + str(e))
                                theplot = (theplot[:350])

                            # This is a TV show
                            if showtitles != None and len(showtitles.group(1)) > 0:
                                season = re.search('"season" *: *(.*?),', f)
                                episode = re.search('"episode" *: *(.*?),', f)
                                swtitle = (titles.group(1)).replace('\\','')
                                swtitle = (swtitle.split('.', 1)[-1]).replace('. ','')
                                
                                try:
                                    seasonval = int(season.group(1))
                                    epval = int(episode.group(1))
                                    swtitle = (('0' if seasonval < 10 else '') + str(seasonval) + 'x' + ('0' if epval < 10 else '') + str(epval) + ' - ' + (swtitle)).replace('  ',' ')
                                except Exception,e:
                                    self.log("Season/Episode formatting failed" + str(e))
                                    seasonval = -1
                                    epval = -1

                                if REAL_SETTINGS.getSetting('EnhancedGuideData') == 'true':  
                                    print 'EnhancedGuideData' 

                                    if imdbnumber == 0:
                                        imdbnumber = self.getTVDBID(showtitles.group(1), year)
                                            
                                    if genre == 'Unknown':
                                        genre = (self.getGenre(type, showtitles.group(1), year))
                                        
                                    if rating == 'NR':
                                        rating = (self.getRating(type, showtitles.group(1), year, imdbnumber))

                                    if imdbnumber != 0:
                                        Managed = self.sbManaged(imdbnumber)

                                GenreLiveID = [genre, type, imdbnumber, dbid, Managed, playcount, rating] 
                                genre, LiveID = self.packGenreLiveID(GenreLiveID)
                                
                                tmpstr += (showtitles.group(1)) + "//" + swtitle + "//" + theplot + "//" + genre + "////" + (LiveID)
                                istvshow = True

                            else:
                                if year != 0:
                                    tmpstr += titles.group(1) + ' (' + str(year) + ')' + "//"
                                else:
                                    tmpstr += titles.group(1) + "//"
                                    
                                album = re.search('"album" *: *"(.*?)"', f)

                                # This is a movie
                                if not album or len(album.group(1)) == 0:
                                    taglines = re.search('"tagline" *: *"(.*?)"', f)
                                    
                                    if taglines != None and len(taglines.group(1)) > 0:
                                        tmpstr += (taglines.group(1)).replace('\\','')
                                    
                                    if REAL_SETTINGS.getSetting('EnhancedGuideData') == 'true':     
                                    
                                        if imdbnumber == 0:
                                            imdbnumber = self.getIMDBIDmovie(titles.group(1), year)

                                        if genre == 'Unknown':
                                            genre = (self.getGenre(type, titles.group(1), year))

                                        if rating == 'NR':
                                            rating = (self.getRating(type, titles.group(1), year, imdbnumber))

                                    if imdbnumber != 0:
                                        Managed = self.cpManaged(titles.group(1), imdbnumber)
                                            
                                    GenreLiveID = [genre, type, imdbnumber, dbid, Managed, playcount, rating]
                                    genre, LiveID = self.packGenreLiveID(GenreLiveID)           
                                    tmpstr += "//" + theplot + "//" + (genre) + "////" + (LiveID)
                                
                                else: #Music
                                    LiveID = 'music|0|0|False|1|NR|'
                                    artist = re.search('"artist" *: *"(.*?)"', f)
                                    tmpstr += album.group(1) + "//" + artist.group(1) + "//" + 'Music' + "////" + LiveID
                            
                            file = unquote(match.group(1))
                            tmpstr = tmpstr
                            tmpstr = tmpstr.replace("\\n", " ").replace("\\r", " ").replace("\\\"", "\"")
                            tmpstr = tmpstr + '\n' + file.replace("\\\\", "\\")
                            
                            if self.channels[channel - 1].mode & MODE_ORDERAIRDATE > 0:
                                seasoneplist.append([seasonval, epval, tmpstr])                        
                            else:
                                fileList.append(tmpstr)
                    except Exception,e:
                        self.log('buildFileList, failed...' + str(e))
                        pass
            else:
                continue

        if self.channels[channel - 1].mode & MODE_ORDERAIRDATE > 0:
            seasoneplist.sort(key=lambda seep: seep[1])
            seasoneplist.sort(key=lambda seep: seep[0])

            for seepitem in seasoneplist:
                fileList.append(seepitem[2])

        if filecount == 0:
            self.logDebug(json_folder_detail)

        self.log("buildFileList return")
        
        #fileList = self.remDupes(fileList)
        return fileList


    def buildMixedFileList(self, dom1, channel):
        self.log('buildMixedFileList')
        fileList = []
        limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]

        try:
            rules = dom1.getElementsByTagName('rule')
            order = dom1.getElementsByTagName('order')
        except Exception,e:
            self.log('buildMixedFileList Problem parsing playlist ' + filename, xbmc.LOGERROR)
            xml.close()
            
            #fileList = self.remDupes(fileList)
            return fileList

        for rule in rules:
            rulename = rule.childNodes[0].nodeValue

            if FileAccess.exists(xbmc.translatePath('special://profile/playlists/video/') + rulename):
                FileAccess.copy(xbmc.translatePath('special://profile/playlists/video/') + rulename, MADE_CHAN_LOC + rulename)
                fileList.extend(self.buildFileList(MADE_CHAN_LOC + rulename, channel, limit, 0))
            else:
                fileList.extend(self.buildFileList(GEN_CHAN_LOC + rulename, channel, limit, 0))

        self.log("buildMixedFileList returning")
        
        #fileList = self.remDupes(fileList)
        return fileList


    def fillLiveTVFileList(self, fileList, CHname, channel):
        self.log("fillLiveTVFileList")
        newList = []
        n = 0
        now = str(datetime.datetime.now())
        now = now.split('.')[0]
        now = datetime.datetime.strptime(now, '%Y-%m-%d %H:%M:%S')
        nowDate = str(datetime.datetime.utcnow())
        nowDate = nowDate.split('.')[0]
        nowDate = datetime.datetime.strptime(nowDate, '%Y-%m-%d %H:%M:%S')
        
        if len(fileList) != 0:
            for i in range(len(fileList)):
                tmpstrLST = (fileList[i]).split('\n')[0]
                file = (fileList[i]).split('\n')[1]
                Dur = tmpstrLST.split(',')[0]
                startDate = tmpstrLST.split('//')[4]
                startDate = datetime.datetime.strptime(startDate, '%Y-%m-%d %H:%M:%S')
                today = nowDate
                tomorrow = nowDate + datetime.timedelta(days=n)
                
                if (today.day == startDate.day and today.hour < startDate.hour) or (tomorrow.day < startDate.day):
                    print 'match'
                    startDur = int(self.__total_seconds__(startDate - nowDate))
                    # startDur = int((startDate - nowDate).total_seconds())
                    tmpstr = str(startDur) + ',' + CHname + "//" + 'SmoothStreams - LiveTV' + "//" + CHname + "//" + 'Unknown' + "//" + str(now) + "//" + 'tvshow|0|0|False|1|NA|' + '\n' + file
                    newList.append(tmpstr)

                tmpstr = tmpstrLST +'\n'+ file
                newList.append(tmpstr)
                n +=1
        else:
            print 'Empty LiveTV FileList, adding tmpstr'
            self.ResetChanLST.insert(0, channel)
            REAL_SETTINGS.setSetting('ResetChanLST', str(self.ResetChanLST))
            tmpstr = str(5400) + ',' + 'Listing Unavailable' + "//" + 'LiveTV' + "//" + 'TV Listing Unavailable, Check your xmltv file' + "//" + 'Unknown' + "//" + str(now) + "//" + 'tvshow|0|0|False|1|NA|' + '\n' + CHname
            newList.append(tmpstr)
            
        return newList
    
    
    def __total_seconds__(self, delta):
        try:
            return delta.total_seconds()
        except AttributeError:
            # *Thanks sphere, taken from plugin.video.ted.talks
            # People still using Python <2.7 201303 :(
            return float((delta.microseconds + (delta.seconds + delta.days * 24 * 3600) * 10 ** 6)) / 10 ** 6

    
    def parseXMLTVDate(self, dateString, offset):
        if dateString is not None:
            if dateString.find(' ') != -1:
                # remove timezone information
                dateString = dateString[:dateString.find(' ')]
            t = time.strptime(dateString, '%Y%m%d%H%M%S')
            d = datetime.datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)
            d += datetime.timedelta(hours = offset)
            return d
        else:
            return None
    
    
    def buildLiveTVFileList(self, setting1, setting2, setting3, setting4, channel):
        xbmc.log("buildLiveTVFileList Cache")
        if Cache_Enabled == True and REAL_SETTINGS.getSetting('EnhancedGuideData') == 'true':  
            try:
                result = liveTV.cacheFunction(self.buildLiveTVFileList_NEW, setting1, setting2, setting3, setting4, channel)
            except:
                result = self.buildLiveTVFileList_NEW(setting1, setting2, setting3, setting4, channel)
                pass
        else:
            result = self.buildLiveTVFileList_NEW(setting1, setting2, setting3, setting4, channel)
        if not result:
            result = []
        return result  
        
    
    def buildLiveTVFileList_NEW(self, setting1, setting2, setting3, setting4, channel):
        self.log("buildLiveTVFileList_NEW")
        showList = []
        showcount = 0 
        playcount = 1
        limit = 48
        id = 0
        rating = 'NR'
        LiveID = 'tvshow|0|0|False|1|NR|'
        Managed = False
        episodeName = ''
        episodeDesc = ''
        episodeGenre = ''
        seasonNumber = 0
        episodeNumber = 0
        tvdbid = 0
        dd_progid = ''
        genre = 'Unknown'
        self.log("buildLiveTVFileList, Using Global Parse-limit " + str(limit))
        
        try:
            if setting3.startswith('http'):
                f = Open_URL(self.xmlTvFile)
            else:
                f = FileAccess.open(self.xmlTvFile, "rb")
                
            if setting3.lower() in UTC_XMLTV:
                GMToffset = True                  
                #our difference from GMT in hours, minus 4 hours for the initial offset of the tv guide data                
                offset = ((time.timezone / 3600) - 5 ) * -1        
            else:
                GMToffset = False
                offset = 0
                
            self.log("buildLiveTVFileList, GMToffset = " + str(GMToffset))
            
            if self.background == False:
                self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding LiveTV", 'parsing ' + str(setting3.lower()))

            context = ET.iterparse(f, events=("start", "end")) 
            context = iter(context)
            event, root = context.next() 
            
            for event, elem in context:
                if self.threadPause() == False:
                    del showList[:]
                    break
                    
                if event == "end":
                    if elem.tag == "programme":
                        channel = elem.get("channel")
                        url = unquote(setting2)
                        
                        if setting1 == channel:
                            title = elem.findtext('title')
                            
                            try:
                                title = title.split("*")[0] #Remove "*" from title
                                playcount = 0
                            except Exception,e:
                                playcount = 1
                                pass

                            description = elem.findtext("desc")
                            iconElement = elem.find("icon")
                            icon = None
                            
                            # todo download channel icon for EPG guide.
                            if iconElement is not None:
                                icon = iconElement.get("src")
                                if icon[0:4] == 'http' and REAL_SETTINGS.getSetting('EnhancedGuideData') == 'true':
                                    chname = (self.getChannelName(8, channel))
                                    self.GrabLogo(icon, chname)
                                
                            subtitle = elem.findtext("sub-title")
                            if not description:
                                if not subtitle:
                                    description = title  
                                else:
                                    description = subtitle
                                    
                            if not subtitle:                        
                                    subtitle = 'LiveTV'

                            ##################################
                            #Parse the category of the program
                            movie = False
                            category = 'Unknown'
                            categories = ''
                            categoryList = elem.findall("category")
                            
                            for cat in categoryList:
                                categories += ', ' + cat.text
                                if cat.text == 'Movie':
                                    movie = True
                                    category = cat.text
                                elif cat.text == 'Sports':
                                    category = cat.text
                                elif cat.text == 'Children':
                                    category = 'Kids'
                                elif cat.text == 'Kids':
                                    category = cat.text
                                elif cat.text == 'News':
                                    category = cat.text
                                elif cat.text == 'Comedy':
                                    category = cat.text
                                elif cat.text == 'Drama':
                                    category = cat.text
                            
                            #Trim prepended comma and space (considered storing all categories, but one is ok for now)
                            categories = categories[2:]
                            
                            #If the movie flag was set, it should override the rest (ex: comedy and movie sometimes come together)
                            if movie == True:
                                category = 'Movie'
                                type = 'movie'
                            else:
                                type = 'tvshow'
                                
                            #TVDB/TMDB Parsing    
                            #filter unwanted ids by title
                            if title == ('Paid Programming') or subtitle == ('Paid Programming') or description == ('Paid Programming'):
                                ignoreParse = True
                            else:
                                ignoreParse = False

                            now = datetime.datetime.now()
                            stopDate = self.parseXMLTVDate(elem.get('stop'), offset)
                            startDate = self.parseXMLTVDate(elem.get('start'), offset)
                            
                            #Enable Enhanced Parsing
                            if REAL_SETTINGS.getSetting('EnhancedGuideData') == 'true' and ignoreParse == False: 
                                if (((now > startDate and now <= stopDate) or (now < startDate))):
                                    if type == 'tvshow':
                                                                            
                                        try:
                                            year = (title.split(' ('))[1].replace(')','')
                                            title = (title.split(' ('))[0]
                                        except:
                                            year = ''
                                            pass
                                
                                        if year:
                                            titleYR = title + ' (' + str(year) + ')'
                                        else:
                                            titleYR = title 
                                
                                        #Decipher the TVDB ID by using the Zap2it ID in dd_progid
                                        episodeNumList = elem.findall("episode-num")
                                        
                                        for epNum in episodeNumList:
                                            if epNum.attrib["system"] == 'dd_progid':
                                                dd_progid = epNum.text
                                        
                                        #The Zap2it ID is the first part of the string delimited by the dot
                                        #  Ex: <episode-num system="dd_progid">MV00044257.0000</episode-num>
                                        
                                        dd_progid = dd_progid.split('.',1)[0]
                                        tvdbid = self.getTVDBIDbyZap2it(dd_progid)

                                        if tvdbid == 0: 
                                            tvdbid = self.getTVDBID(title, year)
                                                      
                                        #Find Episode info by subtitle (ie Episode Name). 
                                        if subtitle != 'LiveTV':
                                            episodeName, seasonNumber, episodeNumber = self.getTVINFObySubtitle(titleYR, subtitle)                                       
                                        else:
                                            #Find Episode info by air date.
                                            if tvdbid != 0:
                                                #Date element holds the original air date of the program
                                                airdateStr = elem.findtext('date')
                                                if airdateStr != None:
                                                    print 'buildLiveTVFileList, tvdbid by airdate'
                                                    try:
                                                        #Change date format into the byAirDate lookup format (YYYY-MM-DD)
                                                        t = time.strptime(airdateStr, '%Y%m%d')
                                                        airDateTime = datetime.datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)
                                                        airdate = airDateTime.strftime('%Y-%m-%d')
                                                        #Only way to get a unique lookup is to use TVDB ID and the airdate of the episode
                                                        episode = ET.fromstring(self.tvdbAPI.getEpisodeByAirdate(tvdbid, airdate))
                                                        episode = episode.find("Episode")
                                                        seasonNumber = episode.findtext("SeasonNumber")
                                                        episodeNumber = episode.findtext("EpisodeNumber")
                                                        episodeDesc = episode.findtext("Overview")
                                                        episodeName = episode.findtext("EpisodeName")
                                                        try:
                                                            int(seasonNumber)
                                                            int(episodeNumber)
                                                        except:
                                                            seasonNumber = 0
                                                            episodeNumber = 0
                                                            pass
                                                    except Exception,e:
                                                        pass

                                        # Find Episode info by SeasonNum x EpisodeNum
                                        if (seasonNumber != 0 and episodeNumber != 0):
                                            episodeName, episodeDesc, episodeGenre = self.getTVINFObySE(titleYR, seasonNumber, episodeNumber)
                                        
                                        if episodeName:
                                            subtitle = episodeName

                                        if episodeDesc:
                                            description = episodeDesc                                              

                                        if episodeGenre and category == 'Unknown':
                                            category = episodeGenre
                                    
                                    else:#Movie
                                        try:
                                            year = (title.split(' ('))[1].replace(')','')
                                            title = (title.split(' ('))[0]
                                        except:
                                            #Date element holds the original air date of the program
                                            year = elem.findtext('date')
                                            pass
                                        
                                        imdbid, plot, tagline, genre = self.getMovieINFObyTitle(title, year)

                                        if imdbid == 0: 
                                            imdbid = self.getIMDBIDmovie(title, year)
                                            
                                        if plot:
                                            description = plot 
                                            
                                        if tagline:
                                            subtitle = tagline
                                            
                                        if genre and genre != 'Unknown':
                                            category = genre

                                    if type == 'tvshow':
                                        id = tvdbid
                                    else:
                                        id = imdbid
                                        
                                    if id != 0:
                                        if type == 'tvshow':
                                            Managed = self.sbManaged(tvdbid)
                                        else:
                                            Managed = self.cpManaged(title, imdbid)
                        
                                        rating = self.getRating(type, title, year, id)
                                                                            
                                        if category == 'Unknown':
                                            genre = (self.getGenre(type, title, year))
                                            if genre:
                                                category = genre

                            if seasonNumber > 0:
                                seasonNumber = '%02d' % int(seasonNumber)
                            
                            if episodeName > 0:
                                episodeNumber = '%02d' % int(episodeNumber)
                                     
                            #Read the "new" boolean for this program
                            if elem.find("new") != None:
                                playcount = 0
                            else:
                                playcount = 1                        
                                
                            GenreLiveID = [category,type,id,0,Managed,playcount,rating] 
                            genre, LiveID = self.packGenreLiveID(GenreLiveID)
                            description = description.replace("\n", "").replace("\r", "")
                            subtitle = subtitle.replace("\n", "").replace("\r", "")
                            
                            try:
                                description = (self.trim(description, 350, '...'))
                            except Exception,e:
                                self.log("description Trim failed" + str(e))
                                description = (description[:350])
                                pass
                                
                            try:
                                subtitle = (self.trim(subtitle, 350, ''))
                            except Exception,e:
                                self.log("subtitle Trim failed" + str(e))
                                subtitle = (subtitle[:350])
                                pass
                            
                            #skip old shows that have already ended
                            if now > stopDate:
                                continue
                            
                            #adjust the duration of the current show
                            if now > startDate and now <= stopDate:
                                try:
                                    dur = ((stopDate - startDate).seconds)
                                except Exception,e:
                                    dur = 3600  #60 minute default
                                    raise
                                    
                            #use the full duration for an upcoming show
                            if now < startDate:
                                try:
                                    dur = (stopDate - startDate).seconds
                                except Exception,e:
                                    dur = 3600  #60 minute default
                                    raise
                                
                            if type == 'tvshow':
                                episodetitle = (('0' if seasonNumber < 10 else '') + str(seasonNumber) + 'x' + ('0' if episodeNumber < 10 else '') + str(episodeNumber) + ' - '+ (subtitle)).replace('  ',' ')

                                if str(episodetitle[0:5]) == '00x00':
                                    episodetitle = episodetitle.split("- ", 1)[-1]
                                    
                                tmpstr = str(dur) + ',' + title + "//" + episodetitle + "//" + description + "//" + genre + "//" + str(startDate) + "//" + LiveID + '\n' + url
                            
                            else: #Movie
                                tmpstr = str(dur) + ',' + title + "//" + subtitle + "//" + description + "//" + genre + "//" + str(startDate) + "//" + LiveID + '\n' + url
                        
                            tmpstr = tmpstr.replace("\\n", " ").replace("\\r", " ").replace("\\\"", "\"")
                            showList.append(tmpstr)
                            showcount += 1
                            
                            if showcount > limit:
                                break

                            if self.background == False:
                                self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding LiveTV, parsing " + str(setting3.lower()), "added " + str(showcount) + " entries")
                
                root.clear()
        except Exception,e:
            self.log("buildLiveTVFileList, Error: " + str(e))
            pass
                
        return showList

    
    def buildInternetTVFileList(self, setting1, setting2, setting3, setting4, channel):
        self.log('buildInternetTVFileList')
        showList = []
        seasoneplist = []
        showcount = 0
        dur = 0
        url = ''
        title = ''
        description = ''
        LiveID = 'tvshow|0|0|False|1|NR|'  
        
        if self.background == False:
            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding InternetTV", str(setting3))

        url = unquote(setting2)
        title = setting3
        description = setting4
        if not description:
            description = title
        istvshow = True

        if setting1 != '':
            dur = setting1
        else:
            dur = 5400  #90 minute default
            
        self.log("buildInternetTVFileList, CHANNEL: " + str(self.settingChannel) + ", " + title + "  DUR: " + str(dur))
        tmpstr = str(dur) + ',' + title + "//" + "InternetTV" + "//" + description + "//" 'InternetTV' + "////" + LiveID + '\n' + url
        tmpstr = tmpstr.replace("\\n", " ").replace("\\r", " ").replace("\\\"", "\"")
        showList.append(tmpstr)
        return showList


    def createYoutubeFilelist(self, setting1, setting2, setting3, setting4, channel):
        xbmc.log("createYoutubeFilelist Cache")
        if Cache_Enabled == True:
            try:
                if self.seasonal:
                    result = seasonal.cacheFunction(self.createYoutubeFilelist_NEW, setting1, setting2, setting3, setting4, channel)
                else:
                    result = YoutubeTV.cacheFunction(self.createYoutubeFilelist_NEW, setting1, setting2, setting3, setting4, channel)
            except:
                result = self.createYoutubeFilelist_NEW(setting1, setting2, setting3, setting4, channel)
                pass
        else:
            result = self.createYoutubeFilelist_NEW(setting1, setting2, setting3, setting4, channel)
        if not result:
            result = []
        return result  
        
     
    def createYoutubeFilelist_NEW(self, setting1, setting2, setting3, setting4, channel):
        self.log("createYoutubeFilelist")
        showList = []
        showcount = 0
        stop = 0
        LiveID = 'tvshow|0|0|False|1|NR|'
        
        if self.youtube_ok != False:
        
            if setting3 == '':
                limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
                if limit == 0 or limit > 200:
                    limit = 200
                elif limit < 25:
                    limit = 25
                self.log("createYoutubeFilelist, Using Global Parse-limit " + str(limit))
            else:
                limit = int(setting3)
                self.log("createYoutubeFilelist, Overriding Parse-limit = " + str(limit))
                
            if setting2 == '1' or setting2 == '3' or setting2 == '4':
                stop = (limit / 25)
                YTMSG = 'Channel ' + setting1
            elif setting2 == '2':
                stop = (limit / 25)
                YTMSG = 'Playlist ' + setting1
            elif setting2 == '5':
                stop = (limit / 25)
                YTMSG = 'Search Querys'
            elif setting2 == '7':
                YTMSG = 'MultiTube Playlists'
                showList = self.BuildMultiYoutubeChannelNetwork(setting1, setting2, setting3, setting4, channel)
            elif setting2 == '8':
                YTMSG = 'MultiTube Channels'
                showList = self.BuildMultiYoutubeChannelNetwork(setting1, setting2, setting3, setting4, channel)
            elif setting2 == '9': 
                stop = 1 # If Setting2 = User playlist pagination disabled, else loop through pagination of 25 entries per page and stop at limit.
                YTMSG = 'Raw gdata'
            elif setting2 == '31':
                YTMSG = 'Seasons Channel'
                showList = self.BuildseasonalYoutubeChannel(setting1, setting2, setting3, setting4, channel)

            if self.background == False:
                if REAL_SETTINGS.getSetting('commercials') == '2' or REAL_SETTINGS.getSetting('AsSeenOn') == 'true':
                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Youtube", "")
                else:
                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Youtube", "parsing " + str(YTMSG))     
            startIndex = 1
            
            for x in range(stop):    
                if self.threadPause() == False:
                    del showList[:]
                    break
                    
                setting1 = setting1.replace(' ', '+')
                if setting2 == '1': #youtube user uploads
                    youtubechannel = 'http://gdata.youtube.com/feeds/api/users/' +setting1+ '/uploads?start-index=' +str(startIndex)+ '&max-results=25'
                    youtube = youtubechannel
                elif setting2 == '2': #youtube playlist 
                    youtubeplaylist = 'https://gdata.youtube.com/feeds/api/playlists/' +setting1+ '?start-index=' +str(startIndex)
                    youtube = youtubeplaylist                        
                elif setting2 == '3': #youtube new subscriptions
                    youtubesubscript = 'http://gdata.youtube.com/feeds/api/users/' +setting1+ '/newsubscriptionvideos?start-index=' +str(startIndex)+ '&max-results=25'
                    youtube = youtubesubscript                  
                elif setting2 == '4': #youtube favorites
                    youtubefavorites = 'https://gdata.youtube.com/feeds/api/users/' +setting1+ '/favorites?start-index=' +str(startIndex)+ '&max-results=25'
                    youtube = youtubefavorites      
                elif setting2 == '5': #youtube search
                    try:
                        safe = setting1.split('|')[0]
                        setting1 = setting1.split('|')[1]
                    except Exception,e:
                        safe = 'none'
                    youtubesearchVideo = 'https://gdata.youtube.com/feeds/api/videos?q=' +setting1+ '&start-index=' +str(startIndex)+ '&max-results=25&safeSearch=' +safe+ '&v=2'
                    youtube = youtubesearchVideo    
                elif setting2 == '9': #youtube raw gdata
                    youtube = setting1

                feed = feedparser.parse(youtube)   
                self.log("createYoutubeFilelist, " + YTMSG + " " + setting1)  
                self.log('createYoutubeFilelist, youtube = ' + str(youtube))                
                startIndex = startIndex + 25
                    
                for i in range(len(feed['entries'])):
                    try:
                        showtitle = feed.channel.author_detail['name']
                        showtitle = showtitle.replace(":", "").replace('YouTube', setting1)
                        
                        try:
                            genre = (feed.entries[0].tags[1]['term'])
                        except Exception,e:
                            self.log("createYoutubeFilelist, Invalid genre")
                            genre = 'Youtube'
                        
                        try:
                            thumburl = feed.entries[i].media_thumbnail[0]['url']
                        except Exception,e:
                            self.log("createYoutubeFilelist, Invalid media_thumbnail")
                            pass 
                        
                        try:
                            #Time when the episode was published
                            time = (feed.entries[i].published_parsed)
                            time = str(time)
                            time = time.replace("time.struct_time", "")            
                            
                            #Some channels release more than one episode daily.  This section converts the mm/dd/hh to season=mm episode=dd+hh
                            showseason = [word for word in time.split() if word.startswith('tm_mon=')]
                            showseason = str(showseason)
                            showseason = showseason.replace("['tm_mon=", "")
                            showseason = showseason.replace(",']", "")
                            showepisodenum = [word for word in time.split() if word.startswith('tm_mday=')]
                            showepisodenum = str(showepisodenum)
                            showepisodenum = showepisodenum.replace("['tm_mday=", "")
                            showepisodenum = showepisodenum.replace(",']", "")
                            showepisodenuma = [word for word in time.split() if word.startswith('tm_hour=')]
                            showepisodenuma = str(showepisodenuma)
                            showepisodenuma = showepisodenuma.replace("['tm_hour=", "")
                            showepisodenuma = showepisodenuma.replace(",']", "")
                        except Exception,e:
                            pass
                    
                        try:
                            eptitle = feed.entries[i].title
                            eptitle = re.sub('[!@#$/:]', '', eptitle)
                            eptitle = uni(eptitle)
                            eptitle = re.sub("[\W]+", " ", eptitle.strip()) 
                        except Exception,e:
                            eptitle = setting1
                            eptitle = eptitle.replace('+',', ')
                        
                        try:
                            showtitle = (self.trim(showtitle, 350, ''))
                        except Exception,e:
                            self.log("showtitle Trim failed" + str(e))
                            showtitle = (showtitle[:350])
                            pass
                        showtitle = showtitle.replace('/','')
                        
                        try:
                            eptitle = (self.trim(eptitle, 350, ''))
                        except Exception,e:
                            self.log("eptitle Trim failed" + str(e))
                            eptitle = (eptitle[:350])  
                        
                        try:
                            summary = feed.entries[i].summary
                            summary = (summary)
                            summary = re.sub("[\W]+", " ", summary.strip())                       
                        except Exception,e:
                            summary = showtitle +' - '+ eptitle
                        
                        try:
                            summary = (self.trim(summary, 350, '...'))
                        except Exception,e:
                            self.log("summary Trim failed" + str(e))
                            summary = (summary[:350])

                        #remove // because interferes with playlist split.
                        summary = self.CleanLabels(summary)
                            
                        try:
                            runtime = feed.entries[i].yt_duration['seconds']
                            self.logDebug('createYoutubeFilelist, runtime = ' + str(runtime))
                            runtime = int(runtime)
                            # runtime = round(runtime/60.0)
                            # runtime = int(runtime)
                        except Exception,e:
                            runtime = 0
     
                        
                        if runtime >= 1:
                            duration = runtime
                        else:
                            duration = 90
                            self.log("createYoutubeFilelist, CHANNEL: " + str(self.settingChannel) + " - Error calculating show duration (defaulted to 90 min)")
                        
                        # duration = round(duration*60.0)
                        self.logDebug('createYoutubeFilelist, duration = ' + str(duration))
                        duration = int(duration)
                        url = feed.entries[i].media_player['url']
                        self.logDebug('createYoutubeFilelist, url.1 = ' + str(url))
                        url = url.replace("https://", "").replace("http://", "").replace("www.youtube.com/watch?v=", "").replace("&feature=youtube_gdata_player", "").replace("?version=3&f=playlists&app=youtube_gdata", "").replace("?version=3&f=newsubscriptionvideos&app=youtube_gdata", "")
                        self.logDebug('createYoutubeFilelist, url.2 = ' + str(url))
                        
                        # Build M3U
                        istvshow = True
                        tmpstr = str(duration) + ',' + eptitle + '//' + "Youtube - " + showtitle + "//" + summary + "//" + genre + "////" + LiveID + '\n' + self.youtube_ok + url
                        tmpstr = tmpstr.replace("\\n", " ").replace("\\r", " ").replace("\\\"", "\"")
                        self.log("createYoutubeFilelist, CHANNEL: " + str(self.settingChannel) + ", " + eptitle + "  DUR: " + str(duration))
                        showList.append(tmpstr)
                        showcount += 1

                        if self.background == False:
                            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Youtube, parsing " + str(YTMSG), "added " + str(showcount) + " entries")
                    
                    except Exception,e:
                        pass
    
        return showList

        
    def BuildseasonalYoutubeChannel(self, setting1, setting2, setting3, setting4, channel):
        self.log("BuildseasonalYoutubeChannel")
        tmpstr = ''
        showList = []
        genre_filter = [setting1.lower()]
        Playlist_List = 'https://pseudotv-live-community.googlecode.com/svn/youtube_playlists_networks.xml'
        
        try:
            f = Open_URL(Playlist_List)
            linesLST = f.readlines()
            linesLST = linesLST[2:]#remove first two lines
            f.close
        except:
            return
            
        for i in range(len(linesLST)):
            line = str(linesLST[i]).replace("\n","").replace('""',"")
            line = line.split("|")
        
            #If List Formatting is bad return
            if len(line) == 7:  
                genre = line[0]
                chtype = line[1]
                setting1 = (line[2]).replace(",","|")
                setting2 = line[3]
                setting3 = line[4]
                setting4 = line[5]
                channel_name = line[6]
                CHname = channel_name

                if genre.lower() in genre_filter:
                    channelList = setting1.split('|')
                    
                    for n in range(len(channelList)):
                        tmpstr = self.createYoutubeFilelist(channelList[n], '2', setting3, setting4, channel)
                        showList.extend(tmpstr) 
        
        return showList    
    
    
    def BuildMultiYoutubeChannelNetwork(self, setting1, setting2, setting3, setting4, channel):
        self.log("BuildMultiYoutubeChannelNetwork")
        
        if setting2 == '7':
            channelList = setting1.split('|')
            tmpstr = ''
            showList = []
            
            for n in range(len(channelList)):
                tmpstr = self.createYoutubeFilelist(channelList[n], '2', setting3, setting4, channel)
                showList.extend(tmpstr)     
        else:
            channelList = setting1.split('|')
            tmpstr = ''
            showList = []
            
            for n in range(len(channelList)):
                tmpstr = self.createYoutubeFilelist(channelList[n], '1', setting3, setting4, channel)
                showList.extend(tmpstr)     
            
        return showList
    
    
    def createRSSFileList(self, setting1, setting2, setting3, setting4, channel):
        xbmc.log("createRSSFileList Cache")
        if Cache_Enabled == True: 
            try:
                result = RSSTV.cacheFunction(self.createRSSFileList_NEW, setting1, setting2, setting3, setting4, channel)
            except:
                result = self.createRSSFileList_NEW(setting1, setting2, setting3, setting4, channel)
                pass
        else:
            result = self.createRSSFileList_NEW(setting1, setting2, setting3, setting4, channel)
        if not result:
            result = []
        return result  
        
    
    def createRSSFileList_NEW(self, setting1, setting2, setting3, setting4, channel):
        self.log("createRSSFileList")
        showList = []
        seasoneplist = []
        showcount = 0
        limit = 0
        stop = 0 
        runtime = 0
        genre = 'Unknown'
        LiveID = 'tvshow|0|0|False|1|NR|'
        
        if setting3 == '':
            limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
            if limit == 0 or limit > 200:
                limit = 200
            elif limit < 25:
                limit = 25
            self.log("createRSSFileList, Using Global Parse-limit " + str(limit))
        else:
            limit = int(setting3)
            self.log("createRSSFileList, Overiding Global Parse-limit to " + str(limit))    
            
        if setting2 == '1':
            stop = 1
        else:
            stop = (limit / 25)
               
            
        if self.background == False:
            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding RSS", "")

        inSet = False
        startIndex = 1
        for x in range(stop):    
            if self.threadPause() == False:
                del showList[:]
                break
                
            if setting2 == '1': #RSS
                self.log("createRSSFileList, RSS " + ", Limit = " + str(limit))
                rssfeed = setting1
                feed = feedparser.parse(rssfeed)

                for i in range(len(feed['entries'])):
                    try:
                        showtitle = feed.channel.title
                        showtitle = showtitle.replace(":", "")
                        eptitle = feed.entries[i].title
                        eptitle = eptitle.replace("/", "-")
                        eptitle = eptitle.replace(":", " ")
                        eptitle = eptitle.replace("\"", "")
                        eptitle = eptitle.replace("?", "")
                        
                        try:
                            showtitle = (self.trim(showtitle, 350, ''))
                        except Exception,e:
                            self.log("showtitle Trim failed" + str(e))
                            showtitle = (showtitle[:350])
                            pass
                        showtitle = showtitle.replace('/','')
                    
                        try:
                            eptitle = (self.trim(eptitle, 350, ''))
                        except Exception,e:
                            self.log("eptitle Trim failed" + str(e))
                            eptitle = (eptitle[:350])
                            
                        if 'author_detail' in feed.entries[i]:
                            studio = feed.entries[i].author_detail['name']  
                        else:
                            self.log("createRSSFileList, Invalid author_detail")  
                            
                        if 'media_thumbnail' in feed.entries[i]:
                            thumburl = feed.entries[i].media_thumbnail[0]['url']
                        else:
                            self.log("createRSSFileList, Invalid media_thumbnail")

                        if not '<p>' in feed.entries[i].summary_detail.value:
                            epdesc = feed.entries[i]['summary_detail']['value']
                            head, sep, tail = epdesc.partition('<div class="feedflare">')
                            epdesc = head
                        else:
                            epdesc = feed.entries[i]['subtitle']
                        
                        if epdesc == '':
                            epdesc = feed.entries[i]['blip_puredescription'] 
                        
                        if epdesc == '':
                            epdesc = eptitle
                            
                        epdesc = epdesc.replace('\n', '').replace('<br />', '\n').replace('&apos;','').replace('&quot;','"')
                        
                        try:
                            epdesc = (self.trim(epdesc, 350, '...'))
                        except Exception,e:
                            self.log("epdesc Trim failed" + str(e))
                            epdesc = (epdesc[:350])
                            
                        epdesc = epdesc.replace('\n','')
                        
                        if 'media_content' in feed.entries[i]:
                            url = feed.entries[i].media_content[0]['url']
                        else:
                            url = feed.entries[i].links[1]['href']
                        
                        try:
                            runtimex = feed.entries[i]['itunes_duration']
                        except Exception,e:
                            runtimex = ''
                            pass

                        try:
                            if runtimex == '':
                                runtimex = feed.entries[i]['blip_runtime']
                        except Exception,e:
                            runtimex = ''
                            pass

                        if runtimex == '':
                            runtimex = 1800
                        
                        try:
                            summary = feed.channel.subtitle
                            summary = summary.replace(":", "")
                        except Exception,e:
                            pass
                        
                        if feed.channel.has_key("tags"):
                            genre = str(feed.channel.tags[0]['term'])
                        
                        try:
                            time = (str(feed.entries[i].published_parsed)).replace("time.struct_time", "")                        
                            showseason = [word for word in time.split() if word.startswith('tm_mon=')]
                            showseason = str(showseason)
                            showseason = showseason.replace("['tm_mon=", "")
                            showseason = showseason.replace(",']", "")
                            showepisodenum = [word for word in time.split() if word.startswith('tm_mday=')]
                            showepisodenum = str(showepisodenum)
                            showepisodenum = showepisodenum.replace("['tm_mday=", "")
                            showepisodenum = showepisodenum.replace(",']", "")
                            showepisodenuma = [word for word in time.split() if word.startswith('tm_hour=')]
                            showepisodenuma = str(showepisodenuma)
                            showepisodenuma = showepisodenuma.replace("['tm_hour=", "")
                            showepisodenuma = showepisodenuma.replace(",']", "")  
                            
                            if len(runtimex) > 4:
                                runtime = runtimex.split(':')[-2]
                                runtimel = runtimex.split(':')[-3]
                                runtime = int(runtime)
                                runtimel = int(runtimel)
                                runtime = runtime + (runtimel*60)
                            if not len(runtimex) > 4:
                                runtimex = int(runtimex)
                                runtime = round(runtimex/60.0)
                                runtime = int(runtime)
                        except Exception,e:
                            pass
                        
                        if runtime >= 1:
                            duration = runtime
                        else:
                            duration = 90
                            
                        duration = round(duration*60.0)
                        duration = int(duration)
                        
                        if 'http://www.youtube.com' in url:
                            url = url.replace("http://www.youtube.com/watch?v=", "").replace("&amp;amp;feature=youtube_gdata", "")
                        
                        tmpstr = str(duration) + ',' + eptitle + "//" + "RSS - " + showtitle + "//" + epdesc + "//" + genre + "////" + LiveID + '\n' + url
                        tmpstr = tmpstr.replace("\\n", " ").replace("\\r", " ").replace("\\\"", "\"")
                        self.log("createRSSFileList, CHANNEL: " + str(self.settingChannel) + ", " + eptitle + "  DUR: " + str(duration))
                        showList.append(tmpstr)
                        showcount += 1
        
                        if self.background == False:
                            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding RSS", 'parsing ' + showtitle)
    
                    except Exception,e:
                        pass
                        
        return showList

     
    def MusicVideos(self, setting1, setting2, setting3, setting4, channel):
        self.log("MusicVideos")
        showList = []
        if setting1 == '1':
            self.log("MusicVideos - LastFM")
            msg_type = "Last.FM"
            PluginCHK = self.youtube_ok
            if PluginCHK != False:
                showList = self.lastFM(setting1, setting2, setting3, setting4, channel)
        elif setting1 == '2':
            self.log("MusicVideos - MyMusicTV")
            PluginCHK = self.plugin_ok('plugin.video.my_music_tv')
            if PluginCHK != False:
                msg_type = "My MusicTV"
                showList = self.myMusicTV(setting1, setting2, setting3, setting4, channel)
                
        return showList
    
    
    def lastFM(self, setting1, setting2, setting3, setting4, channel):
        xbmc.log("lastFM Cache")
        if Cache_Enabled == True: 
            try:
                result = lastfm.cacheFunction(self.lastFM_NEW, setting1, setting2, setting3, setting4, channel)
            except:
                result = self.lastFM_NEW(setting1, setting2, setting3, setting4, channel)
                pass
        else:
            result = self.lastFM_NEW(setting1, setting2, setting3, setting4, channel)
        if not result:
            result = []
        return result  
    
    
    def lastFM_NEW(self, setting1, setting2, setting3, setting4, channel):
        self.log("lastFM_NEW")
        # Sample xml output:
        # <clip>
            # <artist url="http://www.last.fm/music/Tears+for+Fears">Tears for Fears</artist>
            # <track url="http://www.last.fm/music/Tears+for+Fears/_/Everybody+Wants+to+Rule+the+World">Everybody Wants to Rule the World</track>
            # <url>http://www.youtube.com/watch?v=ST86JM1RPl0&amp;feature=youtube_gdata_player</url>
            # <duration>191</duration>
            # <thumbnail>http://i.ytimg.com/vi/ST86JM1RPl0/0.jpg</thumbnail>
            # <rating max="5">4.9660454</rating>
            # <stats hits="1" misses="4" />
        # </clip>
        LiveID = 'music|0|0|False|1|NR|'
        showList = [] 
        LastFMList = []
        tmpstr = ''
        api = 'http://api.tv.timbormans.com/user/'+setting2+'/topartists.xml'
        limit = 0
        duration = 0
        artist = ''
        track = ''
        url = ''
        thumburl = ''
        rating = 0
        eptitle = ''
        epdesc = ''
        showcount = 0
        
        if setting3 == '':
            limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
            if limit == 0 or limit > 200:
                limit = 200
            elif limit < 25:
                limit = 25
            self.log("LastFM, Using Global Parse-limit " + str(limit))
        else:
            limit = int(setting3)
            self.log("LastFM, Overriding Global Parse-limit to " + str(limit))
        
        if self.background == False:
            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Last.FM", "User " + setting2)

        for n in range(limit):

            if self.threadPause() == False:
                del fileList[:]
                break
            
            try:
                file = Open_URL(api)
                self.log('file' + str(file))
                data = file.read()
                self.log('data' + str(data))
                file.close()
                dom = parseString(data)

                xmlartist = dom.getElementsByTagName('artist')[0].toxml()
                artist = xmlartist.replace('<artist>','').replace('</artist>','')
                artist = artist.rsplit('>', -1)
                artist = artist[1]
                # artist = str(artist)
                artist = self.uncleanString(artist)

                xmltrack = dom.getElementsByTagName('track')[0].toxml()
                track = xmltrack.replace('<track url>','').replace('</track>','')
                track = track.rsplit('>', -1)
                track = track[1]
                # track = str(track)
                track = self.uncleanString(track)

                xmlurl = dom.getElementsByTagName('url')[0].toxml()
                url = xmlurl.replace('<url>','').replace('</url>','')  
                url = url.replace("https://", "").replace("http://", "").replace("www.youtube.com/watch?v=", "").replace("&feature=youtube_gdata_player", "").replace("&amp;feature=youtube_gdata_player", "")

                xmlduration = dom.getElementsByTagName('duration')[0].toxml()
                duration = xmlduration.replace('<duration>','').replace('</duration>','')

                xmlthumbnail = dom.getElementsByTagName('thumbnail')[0].toxml()
                thumburl = xmlthumbnail.replace('<thumbnail>','').replace('</thumbnail>','')

                xmlrating = dom.getElementsByTagName('rating')[0].toxml()
                rating = xmlrating.replace('<rating>','').replace('</rating>','')
                rating = rating.rsplit('>', -1)
                rating = rating[1]
                rating = rating[0:4]
                eptitle = uni(artist + ' - ' + track)
                epdesc = uni('Rated ' + rating + '/5.00')
                
                tmpstr = str(duration) + ',' + eptitle + "//" + "Last.FM" + "//" + epdesc + "//" + 'Music' + "////" + LiveID + '\n' + self.youtube_ok + url
                tmpstr = tmpstr.replace("\\n", " ").replace("\\r", " ").replace("\\\"", "\"")
                showList.append(tmpstr)
                showcount += 1    
                          
                if self.background == False:
                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Last.FM, User " + setting2, "added " + str(showcount) + " entries")
                
            except Exception,e:
                pass    
                
        return showList

    
    def myMusicTV(self, setting1, setting2, setting3, setting4, channel):
        self.log("myMusicTV")
        path = xbmc.translatePath("special://profile/addon_data/plugin.video.my_music_tv/cache/plist")
        LiveID = 'music|0|0|False|1|NR|'
        fle = os.path.join(path,setting2+".xml.plist")
        showcount = 0
        MyMusicLST = []

        if setting3 == '':
            limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
            if limit == 0 or limit > 200:
                limit = 200
            elif limit < 25:
                limit = 25
            self.log("myMusicTV, Using Global Parse-limit " + str(limit))
        else:
            limit = int(setting3)
            self.log("myMusicTV, Overriding Parse-limit = " + str(limit))
            
        try:
            if FileAccess.exists(fle):
                f = FileAccess.open(fle, "r")
                lineLST = f.readlines()
                
                if self.background == False:
                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding My MusicTV", setting2)

                for n in range(len(lineLST)):
                    if self.threadPause() == False:
                        del fileList[:]
                        break
                        
                    line = lineLST[n].replace("['",'').replace("']",'').replace('["','').replace("\n",'')
                    line = line.split(", ")
                    title = line[0]
                    link = line[1].replace("'",'')
                    link = link.replace('plugin://plugin.video.youtube/?action=play_video&videoid=', self.youtube_ok)
                    
                    try:
                        id = str(os.path.split(link)[1]).split('?url=')[1]
                        source = str(id).split('&mode=')[1]
                        id = str(id).split('&mode=')[0]
                    except:
                        pass

                    try:
                        artist = title.split(' - ')[0]
                        track = title.split(' - ')[1].replace("'",'')
                    except:
                        artist = title
                        track = ''
                        pass
                    
                    # Parse each source for duration details todo
                    #if source == 'playVevo':
                        #playVevo()
                    # def playVevo(id):
                        # opener = urllib2.build_opener()
                        # userAgent = "Mozilla/5.0 (Windows NT 6.1; rv:30.0) Gecko/20100101 Firefox/30.0"
                        # opener.addheaders = [('User-Agent', userAgent)]
                        # content = opener.open("http://videoplayer.vevo.com/VideoService/AuthenticateVideo?isrc="+id).read()
                        # content = str(json.loads(content))
                        # print content
                    
                    tmpstr = str(300) + ',' + artist + "//" + "My MusicTV" + "//" + track + "//" + 'Music' + "////" + LiveID + '\n' + link
                    tmpstr = tmpstr.replace("\\n", " ").replace("\\r", " ").replace("\\\"", "\"")
                    MyMusicLST.append(tmpstr)
                    showcount += 1    
                    
                    if showcount > limit:
                        break

                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding My MusicTV, " + setting2, "added " + str(showcount) + " entries")
        
            else:
                self.log("myMusicTV, No MyMusic plist cache found = " + str(fle))
                
        
        except Exception,e:  
            pass
            
        return MyMusicLST

        
    def xmltv_ok(self, setting1, setting3):
        self.log("xmltv_ok")
        self.xmltvValid = False
        self.xmlTvFile = ''
        linesLST = []
        lines = ''
        self.log("setting3 = " + str(setting3))
        
        #XMLTV CHECK TEMP DISABLED#
        if setting3 == 'ustvnow':
            self.log("xmltv_ok, testing " + str(setting3))
            # if FileAccess.exists(USTVnowXML):
            self.xmlTvFile = USTVnowXML
            self.xmltvValid = True
            self.log("INFO: XMLTV File Found...")
        elif setting3 == 'smoothstreams':
            self.log("xmltv_ok, testing " + str(setting3))
            # if FileAccess.exists(SSTVXML):
            self.xmlTvFile = SSTVXML
            self.xmltvValid = True
            self.log("INFO: XMLTV File Found...")
        elif setting3 == 'ftvguide':
            self.log("xmltv_ok, testing " + str(setting3))
            # if FileAccess.exists(FTVXML):
            self.xmlTvFile = FTVXML
            self.xmltvValid = True
            self.log("INFO: XMLTV File Found...")
        elif setting3[0:4] == 'http':
            try: 
                urllib2.urlopen(setting3)
                self.log("xmltv_ok, INFO: URL Connected...")
                self.xmlTvFile = setting3
                self.xmltvValid = True
            except urllib2.URLError as e:
                pass
        elif setting3 != '':
            self.xmlTvFile = xbmc.translatePath(os.path.join(REAL_SETTINGS.getSetting('xmltvLOC'), str(setting3) +'.xml'))
            # if FileAccess.exists(self.xmlTvFile):
            self.log("INFO: XMLTV File Found...")
            self.xmltvValid = True          

        self.log("xmltvValid = " + str(self.xmltvValid))
        return self.xmltvValid
                    
        
    def Valid_ok(self, setting2):
        self.log("Valid_ok")
        self.Override_ok = REAL_SETTINGS.getSetting('Override_ok') == "true"
        self.log('Stream Validation Override is ' + str(self.Override_ok))
        
        #Override Check# 
        if self.Override_ok == True:
            self.log("Overriding Stream Validation")
            return True
        #rtmp check
        elif setting2[0:4] == 'rtmp':
            self.rtmpValid = self.rtmpDump(setting2)  
            return self.rtmpValid        
        #http check     
        elif setting2[0:4] == 'http':
            self.urlValid = self.url_ok(setting2)
            return self.urlValid      
        #plugin check  
        elif setting2[0:6] == 'plugin':  
            self.Pluginvalid = self.plugin_ok(setting2)
            return self.Pluginvalid      
        #strm check  
        elif setting2[-4:] == 'strm':         
            self.strmValid = self.strm_ok(setting2)
            return self.strmValid   
        #pvr check
        elif setting2[0:3] == 'pvr':
            return True  
        #upnp check
        elif setting2[0:4] == 'upnp':
            return True 
        #udp check
        elif setting2[0:3] == 'udp':
            return True  
        #rtsp check
        elif setting2[0:4] == 'rtsp':
            return True  
        #HDHomeRun check
        elif setting2[0:9] == 'hdhomerun':
            return True  
        else:
            return False  
  
  
    def strm_ok(self, setting2):
        self.log("strm_ok, " + str(setting2))
        self.strmFailed = False
        self.strmValid = False
        rtmpOK = True
        urlOK = True
        pluginOK = True
        lines = ''
        fallback = INTRO

        try:
            f = FileAccess.open(setting2, "rb")
            linesLST = f.readlines()
            self.log("strm_ok.Lines = " + str(linesLST))
            f.close()

            for i in range(len(set(linesLST))):
                lines = linesLST[i]
                self.strmValid = self.Valid_ok(lines)

                if self.strmValid == False:
                    self.log("strm_ok, failed strmCheck; writing fallback video")
                    f = FileAccess.open(setting2, "w")
                    for i in range(len(linesLST)):
                        lines = linesLST[i]
                        if lines != fallback:
                            f.write(lines + '\n')
                        self.logDebug("strm_ok, file write lines = " + str(lines))
                    f.write(fallback)
                    f.close()
                    self.strmValid = True 
                    
            return self.strmValid
                
        except Exception,e:
            pass
        
        return self.strmValid        

   
    def rtmpDump(self, stream):
        self.rtmpValid = False
        url = unquote(stream)
        
        OSplat = REAL_SETTINGS.getSetting('os')
        if OSplat == '0':
            OSpath = 'androidarm/rtmpdump'
        elif OSplat == '1':
            OSpath = 'android86/rtmpdump'
        elif OSplat == '2':
            OSpath = 'atv1linux/rtmpdump'
        elif OSplat == '3':
            OSpath = 'atv1stock/rtmpdump'
        elif OSplat == '4':
            OSpath = 'atv2/rtmpdump'
        elif OSplat == '5':
            OSpath = 'ios/rtmpdump'
        elif OSplat == '6':
            OSpath = 'linux32/rtmpdump'
        elif OSplat == '7':
            OSpath = 'linux64/rtmpdump'
        elif OSplat == '8':
            OSpath = 'mac32/rtmpdump'
        elif OSplat == '9':
            OSpath = 'mac64/rtmpdump'
        elif OSplat == '10':
            OSpath = 'pi/rtmpdump'
        elif OSplat == '11':
            OSpath = 'win/rtmpdump.exe'
        elif OSplat == '12':
            OSpath = '/usr/bin/rtmpdump'
            
        RTMPDUMP = xbmc.translatePath(os.path.join(ADDON_PATH, 'resources', 'lib', 'rtmpdump', OSpath))
        self.log("RTMPDUMP = " + RTMPDUMP)
        assert os.path.isfile(RTMPDUMP)
        
        if "playpath" in url:
            url = re.sub(r'playpath',"-y playpath",url)
            self.log("playpath url = " + str(url))
            command = [RTMPDUMP, '-B 1', '-m 2', '-r', url,'-o','test.flv']
            self.log("RTMPDUMP command = " + str(command))
        else:
            command = [RTMPDUMP, '-B 1', '-m 2', '-r', url,'-o','test.flv']
            self.log("RTMPDUMP command = " + str(command))
       
        CheckRTMP = Popen(command, shell=True, stdin=PIPE, stdout=PIPE, stderr=STDOUT)
        output = CheckRTMP.communicate()[0]
        self.log("output = " + output)
        
        if "ERROR:" in output:
            self.log("ERROR: Problem accessing the DNS. RTMP URL NOT VALiD")
            self.rtmpValid = False 
        elif "WARNING:" in output:
            self.log("WARNING: Problem accessing the DNS. RTMP URL NOT VALiD")
            self.rtmpValid = False
        elif "INFO: Connected..." in output:
            self.log("INFO: Connected...")
            self.rtmpValid = True
        else:
            self.log("ERROR?: Unknown response...")
            self.rtmpValid = False
        
        self.log("rtmpValid = " + str(self.rtmpValid))
        return self.rtmpValid

        
    def url_ok(self, url):
        self.urlValid = False
        url = unquote(url)
        try: 
            Open_URL(urllib2.Request(url))
            self.log("INFO: Connected...")
            self.urlValid = True
        except urllib2.URLError as e:
            self.log("ERROR: Problem accessing the DNS. HTTP URL NOT VALID, ERROR: " + str(e))
            self.urlValid = False
        
        self.log("urlValid = " + str(self.urlValid))
        return self.urlValid
        

    def plugin_ok(self, plugin):
        self.log("plugin_ok, plugin= " + plugin)
        self.PluginFound = False
        self.Pluginvalid = False
        
        if plugin[0:9] == 'plugin://':
            addon = os.path.split(plugin)[0]
            addon = (plugin.split('/?')[0]).replace("plugin://","")
            addon = self.splitall(addon)[0]
            self.log("plugin id = " + addon)
        else:
            addon = plugin

        if self.addonFileDetails:
            self.log("plugin_ok, Using Cached addonFileDetails")
            file_detail = self.addonFileDetails
        else:
            self.log("plugin_ok, Creating addonFileDetails Cache")
            json_query = ('{"jsonrpc": "2.0", "method": "Addons.GetAddons", "params": {}, "id": 1}')
            json_folder_detail = self.sendJSON(json_query)
            file_detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)
            self.addonFileDetails = file_detail
                   
        try:
            for f in (file_detail):
                addonids = re.search('"addonid" *: *"(.*?)",', f)
                if addonids:
                    addonid = addonids.group(1)
                    if addonid.lower() == addon.lower():
                        print addonid
                        self.PluginFound = True
                        break
                        
            if self.PluginFound == True:
                
                if REAL_SETTINGS.getSetting("plugin_ok_level") == "0":#Low Check
                    self.Pluginvalid = True
                
                elif REAL_SETTINGS.getSetting("plugin_ok_level") == "1":#High Check
                    json_query = ('{"jsonrpc": "2.0", "method": "Files.GetDirectory", "params": {"directory":"%s"}, "id": 1}' % plugin)
                    json_folder_detail = self.sendJSON(json_query)
                    addon_detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)
                    
                    ## TODO ## Search for exact file, true if found.
                    for f in (addon_detail):
                        file = re.search('"file" *: *"(.*?)"', f)
                        
                    if file != None and len(file.group(1)) > 0:
                        self.Pluginvalid = True     
        except:
            pass
            
        print ("PluginFound = " + str(self.PluginFound))
        return self.Pluginvalid
                                
                
    def youtube_duration(self, YTID):
        self.log("youtube_duration")
        try:
            url = 'https://gdata.youtube.com/feeds/api/videos/{0}?v=2'.format(YTID)
            s = urlopen(url).read()
            d = parseString(s)
            e = d.getElementsByTagName('yt:duration')[0]
            a = e.attributes['seconds']
            v = int(a.value)
        except:
            v = 120
            pass
        return v
        
        
    def youtube_player(self):
        self.log("youtube_player")
        Plugin_1 = self.plugin_ok('plugin.video.bromix.youtube')
        Plugin_2 = self.plugin_ok('plugin.video.youtube')
        
        if Plugin_1 == True:
            path = 'plugin://plugin.video.bromix.youtube/?action=play&id='
        elif Plugin_2 == True:
            path = 'plugin://plugin.video.youtube/?action=play_video&videoid='
        else:
            path = False
            
        return path
            
            
    def playon_player(self):
        print ("playon_player")
        PlayonPath = False
        json_query = ('{"jsonrpc": "2.0", "method": "Files.GetSources", "params": {"media":"video"}, "id": 2}')
        json_folder_detail = self.sendJSON(json_query)
        file_detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)

        for f in file_detail:
            labels = re.search('"label" *: *"(.*?)"', f)
            files = re.search('"file" *: *"(.*?)"', f)
            try:
                label = (labels.group(1)).lower()
                upnp = (files.group(1))
                if label == 'playon':
                    PlayonPath = upnp
                    break
            except:
                pass

        return PlayonPath
        
        
    def trim(self, content, limit, suffix):
        if len(content) <= limit:
            return content
        else:
            return content[:limit].rsplit(' ', 1)[0]+suffix

            
    def insertBCTfiles(self, channel, fileList, type):
        self.log("insertBCTfiles")
        self.logDebug("insertBCTfiles, channel = " + str(channel))
        
        bctFileList = []
        newFileList = []
        BumperNum = 0
        BumperLST = []
        CommercialNum = 0
        CommercialLST = []
        TrailerNum = 0
        TrailerLST = []
        fileListNum = len(fileList)
        FileListMediaLST = []
        LiveID = 'tvshow|0|0|False|1|NR|'
        
        chtype = (ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_type'))
        numbumpers = int(REAL_SETTINGS.getSetting("numbumpers")) + 1#number of Bumpers between shows
        numcommercials = int(REAL_SETTINGS.getSetting("numcommercials")) + 1#number of Commercial between shows
        numTrailers = int(REAL_SETTINGS.getSetting("numtrailers")) + 1#number of trailers between shows

        #Bumpers
        if (REAL_SETTINGS.getSetting('bumpers') != "0" and type != 'movies'): # Bumpers not disabled,and is custom or network playlist.
            BumperLST = self.GetBumperList(channel, fileList)#build full Bumper list
            if BumperLST and len(BumperLST) > 0:
                random.shuffle(BumperLST)
            BumperNum = len(BumperLST)#number of Bumpers items in full list
            self.logDebug("insertBCTfiles, Bumpers.numbumpers = " + str(numbumpers))
        
        #Ratings
        if (REAL_SETTINGS.getSetting('bumpers') != "0" and REAL_SETTINGS.getSetting('bumperratings') == 'true' and type == 'movies'):
            fileList = self.GetRatingList(channel, fileList)

        #Commercial
        if REAL_SETTINGS.getSetting('commercials') != '0' and type != 'movies': # commercials not disabled, and not a movie
            CommercialLST = self.GetCommercialList(channel, fileList)#build full Commercial list
            if CommercialLST and len(CommercialLST) > 0:
                random.shuffle(CommercialLST)
            CommercialNum = len(CommercialLST)#number of Commercial items in full list
            self.logDebug("insertBCTfiles, Commercials.numcommercials = " + str(numcommercials))
        
        #Trailers
        if REAL_SETTINGS.getSetting('trailers') != '0': # trailers not disabled, and not a movie
            TrailerLST = self.GetTrailerList(channel, fileList)
            if TrailerLST and len(TrailerLST) > 0:
                random.shuffle(TrailerLST)
            TrailerNum = len(TrailerLST)#number of trailer items in full list
            self.logDebug("insertBCTfiles, trailers.numTrailers = " + str(numTrailers))    

        for i in range(fileListNum):
            bctDur = 0
            bctFileList = []
            BumperMedia = ''
            BumperMediaLST = []
            CommercialMedia = ''
            CommercialMediaLST = []
            trailerMedia = ''
            trailerMediaLST = []
            File = ''
            
            if BumperNum > 0:
                for n in range(numbumpers):
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Bumpers", '')
                    Bumper = random.choice(BumperLST)#random fill Bumper per show by user selected amount
                    BumperDur = int(Bumper.split(',')[0]) #duration of Bumper
                    bctDur += BumperDur
                    BumperMedia = Bumper.split(',', 1)[-1] #link of Bumper
                    BumperMedia = ('#EXTINF:' + str(BumperDur) + ',//////Bumper////' + LiveID + '\n' + uni(BumperMedia))
                    BumperMediaLST.append(BumperMedia)
            
            if CommercialNum > 0:
                for n in range(numcommercials):    
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Commercials", '')
                    Commercial = random.choice(CommercialLST)#random fill Commercial per show by user selected amount
                    CommercialDur = int(Commercial.split(',')[0]) #duration of Commercial
                    bctDur += CommercialDur
                    CommercialMedia = Commercial.split(',', 1)[-1] #link of Commercial
                    CommercialMedia = ('#EXTINF:' + str(CommercialDur) + ',//////Commercial////' + LiveID + '\n' + uni(CommercialMedia))
                    CommercialMediaLST.append(CommercialMedia)

            if TrailerNum > 0:
                for n in range(numTrailers):    
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Trailers", '')
                    trailer = random.choice(TrailerLST)#random fill trailers per show by user selected amount
                    trailerDur = int(trailer.split(',')[0]) #duration of trailer
                    bctDur += trailerDur
                    trailerMedia = trailer.split(',', 1)[-1] #link of trailer
                    trailerMedia = ('#EXTINF:' + str(trailerDur) + ',//////Trailer////' + LiveID + '\n' + uni(trailerMedia))
                    trailerMediaLST.append(trailerMedia)   

            bctFileList.extend(BumperMediaLST)
            bctFileList.extend(CommercialMediaLST)
            bctFileList.extend(trailerMediaLST)
            random.shuffle(bctFileList)       
            
            if len(bctFileList) > 0:                
                File = (fileList[i] + '\n')
            else: 
                File = fileList[i]
                
            File = uni(File + '\n'.join(bctFileList))
            newFileList.append(File)
            
            # #Auto hide "short videos" in this case BCT's
            # ClipLength = [15,30,60,90,120,180,240,300,360,420,460]      
            # for i in range(len(ClipLength)):
                # bctLength = ClipLength[i]
                # if bctLength >= bctDur:
                    # bctLength = i
                # else:
                    # bctLength = 10
                # break
                    
            # REAL_SETTINGS.setSetting("HideClips","true")
            # REAL_SETTINGS.setSetting("ClipLength",str(bctLength))
            
        return newFileList
        
            
    def GetBumperList (self, channel, fileList):
        self.log("GetBumperList")
        BumperCachePath = xbmc.translatePath(os.path.join(BCT_LOC, 'bumpers')) + '/'  
        BumperLST = []
        chtype = (ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_type'))
        
        if chtype == '0':
            setting1 = str(ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_1'))
            directory, filename = os.path.split(setting1)
            filename = (filename.split('.'))
            chname = (filename[0])
        else:
            chname = ADDON_SETTINGS.getSetting("Channel_" + str(channel) + "_1")  
                
        #Local
        if REAL_SETTINGS.getSetting('bumpers') == "1":  
            self.log("GetBumperList - Local")
            PATH = REAL_SETTINGS.getSetting('bumpersfolder')
            PATH = (PATH + chname)
            
            if FileAccess.exists(PATH):
                try:
                    LocalBumperLST = []
                    duration = 0
                    BumperLocalCache = 'Bumper_Local_Cache_' + chname +'.xml'
                    CacheExpired = self.Cache_ok(BumperCachePath, BumperLocalCache) 

                    if CacheExpired == False:
                        BumperLST = self.readCache(BumperCachePath, BumperLocalCache)
                        
                    elif CacheExpired == True: 
                        LocalFLE = ''
                        LocalBumper = ''
                        LocalLST = xbmcvfs.listdir(PATH)[1]
                        for i in range(len(LocalLST)):    
                            if self.background == False:
                                self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Bumpers", "parsing Local Bumpers")
                            LocalFLE = (LocalLST[i])
                            filename = uni(PATH + '/' + LocalFLE)
                            duration = self.videoParser.getVideoLength(filename)
                            if duration == 0:
                                duration = 3
                            
                            if duration > 0:
                                LocalBumper = (str(duration) + ',' + filename)
                                LocalBumperLST.append(LocalBumper)#Put all bumpers found into one List
                        BumperLST.extend(LocalBumperLST)#Put local bumper list into master bumper list.                
                        self.writeCache(BumperLST, BumperCachePath, BumperLocalCache)
                except:
                    pass
                    
        #Internet
        elif REAL_SETTINGS.getSetting('bumpers') == "2":
            self.log("GetBumperList - Internet")
            if self.youtube_ok != False:
                try:
                    InternetBumperLST = []
                    duration = 3
                    BumperInternetCache = 'Bumper_Internet_Cache_' + chname +'.xml'
                    CacheExpired = self.Cache_ok(BumperCachePath, BumperInternetCache) 
                    
                    if CacheExpired == False:
                        BumperLST = self.readCache(BumperCachePath, BumperInternetCache)
                        
                    elif CacheExpired == True: 
                        Bumper_List = 'https://pseudotv-live-community.googlecode.com/svn/bumpers.xml'

                        f = Open_URL(Bumper_List)
                        linesLST = f.readlines()
                        linesLST = linesLST[2:]
                        f.close

                        for i in range(len(Bumper_List)):
                            lines = str(linesLST[i]).replace('\n','')
                            lines = lines.split('|')
                            ChannelName = lines[0]
                            BumperNumber = lines[1]
                            BumperSource = lines[2].split('_')[0]
                            BumperID = lines[2].split('_')[1]

                            if BumperSource == 'vimeo':
                                url = 'plugin://plugin.video.vimeo/?path=/root/video&action=play_video&videoid=' + BumperID
                            else:
                                url = self.youtube_ok + BumperID
                            
                            if chname.lower() == ChannelName.lower():
                                InternetBumper = (str(duration) + ',' + url)
                                InternetBumperLST.append(InternetBumper)
                        BumperLST.extend(InternetBumperLST)#Put local bumper list into master bumper list.                
                        self.writeCache(BumperLST, BumperCachePath, BumperInternetCache)
                except:
                    pass

        return BumperLST     

        
    def GetRatingList(self, channel, fileList):
        self.log("GetRatingList")
        newFileList = []
        self.youtube_ok = self.youtube_player()
        
        if self.youtube_ok != False:
            URL = self.youtube_ok + 'qlRaA8tAfc0'
            Ratings = (['NR','qlRaA8tAfc0'],['R','s0UuXOKjH-w'],['NC-17','Cp40pL0OaiY'],['PG-13','lSg2vT5qQAQ'],['PG','oKrzhhKowlY'],['G','QTKEIFyT4tk'],['18','g6GjgxMtaLA'],['16','zhB_xhL_BXk'],['12','o7_AGpPMHIs'],['6','XAlKSm8D76M'],['0','_YTMglW0yk'])

            for i in range(len(fileList)):
                file = fileList[i]
                lineLST = (fileList[i]).split('movie|')[1]
                mpaa = (lineLST.split('\n')[0]).split('|')[4]
       
                if self.background == False:
                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Ratings", str(mpaa))
                                
                for i in range(len(Ratings)):
                    rating = Ratings[i]        
                    if mpaa == rating[0]:
                        ID = rating[1]
                        URL = self.youtube_ok + ID
                
                tmpstr = '7,//////Rating////' + 'movie|0|0|False|1|'+str(mpaa)+'|' + '\n' + (URL) + '\n' + '#EXTINF:' + file
                newFileList.append(tmpstr)

        return newFileList
    
    
    def GetCommercialList (self, channel, fileList):
        self.log("GetCommercialList")
        CommercialCachePath = xbmc.translatePath(os.path.join(BCT_LOC, 'commercials')) + '/'   
        chtype = ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_type')
        
        if chtype == '0':
            setting1 = str(ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_1'))
            directory, filename = os.path.split(setting1)
            filename = uni(filename.split('.'))
            chname = uni(filename[0])
        else:
            chname = ADDON_SETTINGS.getSetting("Channel_" + str(channel) + "_1")  
            
        PATH = REAL_SETTINGS.getSetting('commercialsfolder')
        LocalCommercialLST = []
        InternetCommercialLST = []
        YoutubeCommercialLST = []
        AsSeenOnCommercialLST = []
        CommercialLST = []
        duration = 0
        
        #Youtube - As Seen On TV
        if REAL_SETTINGS.getSetting('AsSeenOn') == 'true' and REAL_SETTINGS.getSetting('commercials') != '0':
            CommercialAsSeenOnCache = 'Commercial_AsSeenOn_Cache.xml'
            CacheExpired = self.Cache_ok(CommercialCachePath, CommercialAsSeenOnCache) 
            
            if CacheExpired == False:
                AsSeenOnCommercialLST = self.readCache(CommercialCachePath, CommercialAsSeenOnCache)
                CommercialLST.extend(AsSeenOnCommercialLST)  
                
            elif CacheExpired == True:                 
                YoutubeLST = self.createYoutubeFilelist('SG111', '1', '100', '1', channel)
                for i in range(len(YoutubeLST)): 
                
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Commercials", "parsing As Seen On TV")

                    Youtube = YoutubeLST[i]
                    duration = Youtube.split(',')[0]
                    Commercial = Youtube.split('\n', 1)[-1]
                    if Commercial != '' or Commercial != None:
                        AsSeenOnCommercial = (str(duration) + ',' + Commercial)
                        AsSeenOnCommercialLST.append(AsSeenOnCommercial)
                CommercialLST.extend(AsSeenOnCommercialLST)
                self.writeCache(AsSeenOnCommercialLST, CommercialCachePath, CommercialAsSeenOnCache)

        #Local
        if FileAccess.exists(PATH) and REAL_SETTINGS.getSetting('commercials') == '1':
            CommercialLocalCache = 'Commercial_Local_Cache.xml'
            CacheExpired = self.Cache_ok(CommercialCachePath, CommercialLocalCache) 

            if CacheExpired == False:
                LocalCommercialLST = self.readCache(CommercialCachePath, CommercialLocalCache)
                CommercialLST.extend(LocalCommercialLST)  
            elif CacheExpired == True: 
                LocalFLE = ''
                LocalCommercial = ''
                LocalLST = xbmcvfs.listdir(PATH)[1]
                for i in range(len(LocalLST)):    
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Commercials", "parsing Local Commercials")
                    LocalFLE = (LocalLST[i])
                    filename = uni(PATH + LocalFLE)
                    duration = self.videoParser.getVideoLength(filename)
                    if duration == 0:
                        duration = 30
                    
                    if duration > 0:
                        LocalCommercial = (str(duration) + ',' + filename)
                        LocalCommercialLST.append(LocalCommercial)
                CommercialLST.extend(LocalCommercialLST)                
                self.writeCache(LocalCommercialLST, CommercialCachePath, CommercialLocalCache)

        #Youtube
        if REAL_SETTINGS.getSetting('commercials') == '2':
            CommercialYoutubeCache = 'Commercial_Youtube_Cache.xml'
            CacheExpired = self.Cache_ok(CommercialCachePath, CommercialYoutubeCache) 
            
            if CacheExpired == False:
                YoutubeCommercialLST = self.readCache(CommercialCachePath, CommercialYoutubeCache)
                CommercialLST.extend(YoutubeCommercialLST)  
            elif CacheExpired == True:
                YoutubeCommercial = REAL_SETTINGS.getSetting('commercialschannel') # info,type,limit
                YoutubeCommercial = YoutubeCommercial.split(',')
                
                setting1 = YoutubeCommercial[0]
                setting2 = YoutubeCommercial[1]
                setting3 = YoutubeCommercial[2]
                setting4 = YoutubeCommercial[3]
                YoutubeLST = self.createYoutubeFilelist(setting1, setting2, setting3, setting4, channel)
                
                for i in range(len(YoutubeLST)):    
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Commercials", "parsing Youtube Commercials")
                    Youtube = YoutubeLST[i]
                    duration = Youtube.split(',')[0]
                    Commercial = Youtube.split('\n', 1)[-1]
                    if Commercial != '' or Commercial != None:
                        YoutubeCommercial = (str(duration) + ',' + Commercial)
                        YoutubeCommercialLST.append(YoutubeCommercial)
                CommercialLST.extend(YoutubeCommercialLST)
                self.writeCache(YoutubeCommercialLST, CommercialCachePath, CommercialYoutubeCache)

        #Internet (advertolog.com, ispot.tv)
        if REAL_SETTINGS.getSetting('commercials') == '3' and Donor_Downloaded == True:
            CommercialInternetCache = 'Commercial_Internet_Cache.xml'
            CacheExpired = self.Cache_ok(CommercialCachePath, CommercialInternetCache) 

            if CacheExpired == False:
                InternetCommercialLST = self.readCache(CommercialCachePath, CommercialInternetCache)
                CommercialLST.extend(InternetCommercialLST)  
            elif CacheExpired == True:
                try:  
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Commercials", "parsing Internet Commercials")
                    InternetCommercialLST = InternetCommercial(CommercialCachePath)
                    CommercialLST.extend(InternetCommercialLST)  
                    self.writeCache(InternetCommercialLST, CommercialCachePath, CommercialInternetCache)
                except Exception,e:
                    pass
            
        return CommercialLST 
        
    
    def GetTrailerList (self, channel, fileList):
        self.log("GetTrailerList")
        TrailerCachePath = xbmc.translatePath(os.path.join(BCT_LOC, 'trailers')) + '/'  
        chtype = (ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_type'))
        
        if chtype == '0':
            setting1 = str(ADDON_SETTINGS.getSetting('Channel_' + str(channel) + '_1'))
            directory, filename = os.path.split(setting1)
            filename = (filename.split('.'))
            chname = (filename[0])
        else:
            chname = str(ADDON_SETTINGS.getSetting("Channel_" + str(channel) + "_1"))
            
        if chtype == '3' or chtype == '4' or chtype == '5':
            GenreChtype = True
        else:
            GenreChtype = False
        
        PATH = REAL_SETTINGS.getSetting('trailersfolder')
            
        LocalTrailerLST = []
        JsonTrailerLST = []
        YoutubeTrailerLST = []
        TrailerLST = []
        duration = 0
        genre = ''
        
        #Local
        if (FileAccess.exists(PATH) and REAL_SETTINGS.getSetting('trailers') == '1'): 
            TrailerLocalCache = 'Trailer_Local_Cache.xml'
            CacheExpired = self.Cache_ok(TrailerCachePath, TrailerLocalCache) 

            if CacheExpired == False:
                TrailerLST = self.readCache(TrailerCachePath, TrailerLocalCache)
                
            elif CacheExpired == True: 
                LocalFLE = ''
                LocalTrailer = ''
                LocalLST = self.walk(PATH)
                for i in range(len(LocalLST)):    
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Trailers", "parsing Local Trailers")
                    LocalFLE = LocalLST[i]
                    if '-trailer' in LocalFLE:
                        duration = self.videoParser.getVideoLength(LocalFLE)
                        if duration == 0:
                            duration = 120
                    
                        if duration > 0:
                            LocalTrailer = (str(duration) + ',' + LocalFLE)
                            LocalTrailerLST.append(LocalTrailer)
                TrailerLST.extend(LocalTrailerLST)                
                self.writeCache(TrailerLST, TrailerCachePath, TrailerLocalCache)
        
        #XBMC Library - Local Json
        if (REAL_SETTINGS.getSetting('trailers') == '2'):
            json_query = ('{"jsonrpc":"2.0","method":"VideoLibrary.GetMovies","params":{"properties":["genre","trailer","runtime"]}, "id": 1}')
            genre = chname
            if self.youtube_ok != False:
            
                if REAL_SETTINGS.getSetting('trailersgenre') == 'true' and GenreChtype == True:
                    TrailerInternetCache = 'Trailer_Json_Cache_' + genre + '.xml'
                else:
                    TrailerInternetCache = 'Trailer_Json_Cache_All.xml'

                CacheExpired = self.Cache_ok(TrailerCachePath, TrailerInternetCache) 

                if CacheExpired == False:
                    TrailerLST = self.readCache(TrailerCachePath, TrailerInternetCache)
                    
                elif CacheExpired == True:
                
                    if not self.cached_json_detailed_trailers:
                        self.logDebug('GetTrailerList, json_detail creating cache')
                        self.cached_json_detailed_trailers = self.sendJSON(json_query)   
                        json_detail = self.cached_json_detailed_trailers.encode('utf-8')   
                    else:
                        json_detail = self.cached_json_detailed_trailers.encode('utf-8')   
                        self.logDebug('GetTrailerList, json_detail using cache')
                    
                    if REAL_SETTINGS.getSetting('trailersgenre') == 'true' and GenreChtype == True:
                        JsonLST = uni(json_detail.split("},{"))
                        match = [s for s in JsonLST if genre in s]
                        for i in range(len(match)):    
                            if self.background == False:
                                self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Trailers", "parsing Library Genre")
                            duration = 120
                            json = uni(match[i])
                            trailer = json.split(',"trailer":"',1)[-1]
                            if ')"' in trailer:
                                trailer = trailer.split(')"')[0]
                            else:
                                trailer = trailer[:-1]
                            if trailer != '' or trailer != None or trailer != '"}]}':
                                if 'http://www.youtube.com/watch?hd=1&v=' in trailer:
                                    trailer = trailer.replace("http://www.youtube.com/watch?hd=1&v=", self.youtube_ok).replace("http://www.youtube.com/watch?v=", self.youtube_ok)
                                JsonTrailer = (str(duration) + ',' + trailer)
                                if JsonTrailer != '120,':
                                    JsonTrailerLST.append(JsonTrailer)
                        TrailerLST.extend(JsonTrailerLST)
                        self.writeCache(TrailerLST, TrailerCachePath, TrailerInternetCache)
                    else:
                        JsonLST = uni(json_detail.split("},{"))
                        match = [s for s in JsonLST if 'trailer' in s]
                        for i in range(len(match)):    
                            if self.background == False:
                                self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Trailers", "parsing Library Trailers")
                            duration = 120
                            json = uni(match[i])
                            trailer = json.split(',"trailer":"',1)[-1]
                            if ')"' in trailer:
                                trailer = trailer.split(')"')[0]
                            else:
                                trailer = trailer[:-1]
                            if trailer != '' or trailer != None or trailer != '"}]}':
                                if 'http://www.youtube.com/watch?hd=1&v=' in trailer:
                                    trailer = trailer.replace("http://www.youtube.com/watch?hd=1&v=", self.youtube_ok).replace("http://www.youtube.com/watch?v=", self.youtube_ok)
                                JsonTrailer = (str(duration) + ',' + trailer)
                                if JsonTrailer != '120,':
                                    JsonTrailerLST.append(JsonTrailer)
                        TrailerLST.extend(JsonTrailerLST)     
                        self.writeCache(TrailerLST, TrailerCachePath, TrailerInternetCache)

        #Youtube
        if REAL_SETTINGS.getSetting('trailers') == '3':
            YoutubeTrailers = REAL_SETTINGS.getSetting('trailerschannel') # info,type,limit
            YoutubeTrailers = YoutubeTrailers.split(',')
            setting1 = YoutubeTrailers[0]
            setting2 = YoutubeTrailers[1]
            setting3 = YoutubeTrailers[2]
            setting4 = YoutubeTrailers[3]
            
            YoutubeLST = self.createYoutubeFilelist(setting1, setting2, setting3, setting4, channel)
            for i in range(len(YoutubeLST)):    
                if self.background == False:
                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Trailers", "parsing Youtube Trailers")
                Youtube = YoutubeLST[i]
                duration = Youtube.split(',')[0]
                trailer = Youtube.split('\n', 1)[-1]
                if trailer != '' or trailer != None:
                    YoutubeTrailer = (str(duration) + ',' + trailer)
                    YoutubeTrailerLST.append(YoutubeTrailer)
            TrailerLST.extend(YoutubeTrailerLST)

        #Internet
        if REAL_SETTINGS.getSetting('trailers') == '4' and Donor_Downloaded == True:
            TrailerInternetCache = 'Trailer_Internet_Cache.xml'
            CacheExpired = self.Cache_ok(TrailerCachePath, TrailerInternetCache) 

            if CacheExpired == False:
                TrailerLST = self.readCache(TrailerCachePath, TrailerInternetCache)
                
            elif CacheExpired == True:  
                try:   
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(channel), "adding Trailers", "parsing Internet Trailers")
                    TrailerLST = InternetTrailer(TrailerCachePath)
                    self.writeCache(TrailerLST, TrailerCachePath, TrailerInternetCache)
                except Exception,e:
                    pass

        return TrailerLST

        
    def walk(self, path):
        self.logDebug("walk")     
        VIDEO_TYPES = ('.avi', '.mp4', '.m4v', '.3gp', '.3g2', '.f4v', '.mov', '.mkv', '.flv', '.ts', '.m2ts', '.strm')
        video = []
        folders = []
        # multipath support
        if path.startswith('multipath://'):
            # get all paths from the multipath
            paths = path[12:-1].split('/')
            for item in paths:
                folders.append(urllib.unquote_plus(item))
        else:
            folders.append(path)
        for folder in folders:
            if FileAccess.exists(xbmc.translatePath(folder)):
                # get all files and subfolders
                dirs,files = xbmcvfs.listdir(folder)
                for item in files:
                    # filter out all video
                    if os.path.splitext(item)[1].lower() in VIDEO_TYPES:
                        video.append(os.path.join(folder,item))
                for item in dirs:
                    # recursively scan all subfolders
                    video += self.walk(os.path.join(folder,item))
        return video
        
    
    def writeCache(self, thelist, thepath, thefile):
        self.log("writeCache")  
        now = datetime.datetime.today()

        if not FileAccess.exists(os.path.join(thepath)):
            FileAccess.makedirs(os.path.join(thepath))
        
        thefile = uni(thepath + thefile)        
        try:
            fle = FileAccess.open(thefile, "w")
            fle.write("%s\n" % now)
            for item in thelist:
                fle.write("%s\n" % item)
        except Exception,e:
            pass
        
    
    def readCache(self, thepath, thefile):
        self.log("readCache") 
        thelist = []  
        thefile = (thepath + thefile)
        
        if FileAccess.exists(thefile):
            try:
                fle = FileAccess.open(thefile, "r")
                thelist = fle.readlines()
                LastItem = len(thelist) - 1
                thelist.pop(LastItem)#remove last line (empty line)
                thelist.pop(0)#remove first line (datetime)
                fle.close()
            except Exception,e:
                pass
                
            self.logDebug("readCache, thelist.count = " + str(len(thelist)))
            return thelist
    
    
    def Cache_ok(self, thepath, thefile):
        self.log("Cache_ok")   
        CacheExpired = False
        thefile = (thepath + thefile)
        now = datetime.datetime.today()
        self.logDebug("Cache_ok, now = " + str(now))
        
        if FileAccess.exists(thefile):
            try:
                fle = FileAccess.open(thefile, "r")
                cacheline = fle.readlines()
                cacheDate = str(cacheline[0])
                cacheDate = cacheDate.split('.')[0]
                cacheDate = datetime.datetime.strptime(cacheDate, '%Y-%m-%d %H:%M:%S')
                self.logDebug("Cache_ok, cacheDate = " + str(cacheDate))
                cacheDateEXP = (cacheDate + datetime.timedelta(days=30))
                self.logDebug("Cache_ok, cacheDateEXP = " + str(cacheDateEXP))
                fle.close()  
                
                if now >= cacheDateEXP or len(cacheline) == 2:
                    CacheExpired = True         
            except Exception,e:
                self.logDebug("Cache_ok, exception")
        else:
            CacheExpired = True    
            
        self.log("Cache_ok, CacheExpired = " + str(CacheExpired))
        return CacheExpired
    
    
    def loadFavourites(self):
        self.log("loadFavourites")   
        entries = list()
        path = xbmc.translatePath('special://userdata/favourites.xml')
        if FileAccess.exists(path):
            f = open(path)
            xml = f.read()
            f.close()

            try:
                doc = ET.fromstring(xml)
                for node in doc.findall('favourite'):
                    value = node.text
                    if value[0:11] == 'PlayMedia("':
                        value = value[11:-2]
                    elif value[0:10] == 'PlayMedia(':
                        value = value[10:-1]
                    else:
                        continue

                    entries.append(value)
            except ExpatError:
                pass

        return entries
    
    
    def extras(self, setting1, setting2, setting3, setting4, channel):
        self.log("extras")
        limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
        showList = []

        if Donor_Downloaded == True:  
            if setting1.lower() == 'popcorn':
                
                if self.background == False:
                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Extras, parsing BringThePopcorn", "This could take a moment, Please Wait...")
                
                showList = Bringpopcorn(setting2, setting3, setting4, channel)
                
            elif setting1.lower() == 'cinema':
                flename = self.createCinemaExperiencePlaylist()        
                if setting2 != flename:
                    flename == (xbmc.translatePath(setting2))             
                
                PrefileList = self.buildFileList(flename, channel, limit, 0)
                
                if self.background == False:
                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding Extras, populating PseudoCinema Experience", "This could take a moment, Please Wait...")
                
                showList = BuildCinemaExperienceFileList(setting1, setting2, setting3, setting4, channel, PrefileList)

        return showList

    
    def copyanything(self, src, dst):
        try:
            shutil.copytree(src, dst)
        except OSError as exc:
            if exc.errno == errno.ENOTDIR:
                shutil.copy(src, dst)
            else: raise
            
            
    def sbManaged(self, tvdbid):
        self.log("sbManaged")
        sbManaged = False
        if REAL_SETTINGS.getSetting('sickbeard.enabled') == "true":
            try:
                sbManaged = self.sbAPI.isShowManaged(tvdbid)
            except Exception,e:
                pass

        return sbManaged

        
    def cpManaged(self, title, imdbid):
        self.log("cpManaged")
        cpManaged = False
        if REAL_SETTINGS.getSetting('couchpotato.enabled') == "true":
            try:
                r = str(self.cpAPI.getMoviebyTitle(title))
                r = r.split("u'")
                match = [s for s in r if imdbid in s][1]
                if imdbid in match:
                    cpManaged = True
            except Exception,e:
                pass

        return cpManaged

    
    def getGenre(self, type, title, year):
        self.log("getGenre")
        genre = 'Unknown'
        
        try:
            self.log("metahander")
            self.metaget = metahandlers.MetaData(preparezip=False)
            genre = str(self.metaget.get_meta(type, title)['genre'])
            try:
                genre = str(genre.split(',')[0])
            except Exception as e:
                pass
            try:
                genre = str(genre.split(' / ')[0])
            except Exception as e:
                pass
            if not genre or genre == 'Empty' or genre == 'None':
                genre = 'Unknown'
        except Exception,e:
            genre = 'Unknown'
            pass

        if genre == 'Unknown':

            if type == 'tvshow':
                try:
                    self.log("tvdb_api")
                    genre = str((self.t[title]['genre']))
                    try:
                        genre = str((genre.split('|'))[1])
                    except:
                        pass
                    if not genre or genre == 'Empty' or genre == 'None':
                        genre = 'Unknown'
                except Exception,e:
                    genre = 'Unknown'
                    pass
            else:
                self.log("tmdb")
                movieInfo = str(self.tmdbAPI.getMovie(title, year))
                try:
                    genre = str(movieInfo['genres'][0])
                    genre = str(genre.split("u'")[3]).replace("'}",'')
                    if not genre or genre == 'Empty' or genre == 'None':
                        genre = 'Unknown'
                except Exception,e:
                    genre = 'Unknown'
                    pass

        genre = genre.replace('NA','Unknown')
        return genre
        
    
    def cleanRating(self, rating):
        self.log("cleanRating")
        rating = rating.replace('Rated ','').replace('US:','').replace('UK:','').replace('Unrated','NR').replace('NotRated','NR').replace('N/A','NR').replace('NA','NR').replace('Approved','NR')
        return rating
        # rating = rating.replace('Unrated','NR').replace('NotRated','NR').replace('N/A','NR').replace('Approved','NR')
    

    def getRating(self, type, title, year, imdbid):
        self.log("getRating")
        rating = 'NR'

        try:
            self.log("getRating, metahander")     
            self.metaget = metahandlers.MetaData(preparezip=False)
            rating = self.metaget.get_meta(type, title)['mpaa']
            
            if not rating or rating == 'Empty' or rating == 'None':
                rating = 'NR'
        
        except Exception,e:
            pass
        
        if rating == 'NR':
            if type == 'tvshow':
                try:
                    self.log("getRating, tvdb_api")
                    rating = str(self.t[title]['contentrating'])
                    try:
                        rating = rating.replace('|','')
                    except:
                        pass 
                    if not rating or rating == 'Empty' or rating == 'None':
                        rating = 'NR'
                except Exception,e:
                    rating = 'NR'
                    pass
            else:
                if imdbid and imdbid != 0:
                    try:
                        self.log("getRating, tmdb")
                        rating = str(self.tmdbAPI.getMPAA(imdbid)) 
                        if not rating or rating == 'Empty' or rating == 'None':
                            rating = 'NR'
                    except Exception,e:
                        rating = 'NR'
                        pass

        rating = (self.cleanRating(rating))
        print rating
        return rating

        
    def getTVDBID(self, title, year):
        print 'getTVDBID'
        tvdbid = 0
        if year:
            title = title + ' (' + str(year) + ')'
            
        try:
            self.log("getTVDBID, metahander")
            self.metaget = metahandlers.MetaData(preparezip=False)
            tvdbid = self.metaget.get_meta('tvshow', title)['tvdb_id']
            if not tvdbid or tvdbid == 'Empty':
                tvdbid = 0
        except Exception,e:
            tvdbid = 0
            pass

        if tvdbid == 0:
            try:
                self.log("getTVDBID, tvdb_api")
                tvdbid = int(self.t[title]['id'])
            except Exception,e:
                tvdbid = 0
                pass

        if tvdbid == 0:
            try:
                self.log("getTVDBID, getTVDBIDbyIMDB")
                imdbid = self.getIMDBIDtv(title)
                if imdbid:
                    tvdbid = int(self.getTVDBIDbyIMDB(imdbid))
                if not tvdbid or tvdbid == 'Empty':
                    tvdbid = 0
            except Exception,e:
                tvdbid = 0
                pass

        return tvdbid


    def getIMDBIDtv(self, title):
        print 'getIMDBIDtv'
        imdbid = 0

        try:
            self.log("metahander")
            self.metaget = metahandlers.MetaData(preparezip=False)
            imdbid = self.metaget.get_meta('tvshow', title)['imdb_id']
        except Exception,e:
            pass

        if not imdbid or imdbid == 0:
            try:
                self.log("tvdb_api")
                imdbid = self.t[title]['imdb_id']
                if not imdbid:
                    imdbid = 0
            except Exception,e:
                pass

        if not imdbid or imdbid == 'None' or imdbid == 'Empty':
            imdbid = 0

        return imdbid


    def getTVDBIDbyIMDB(self, imdbid):
        print 'getTVDBIDbyIMDB'
        tvdbid = 0

        try:
            tvdbid = self.tvdbAPI.getIdByIMDB(imdbid)
        except Exception,e:
            pass

        if not tvdbid or tvdbid == 'None' or tvdbid == 'Empty':
            tvdbid = 0
            
        return tvdbid

        
    def getIMDBIDmovie(self, showtitle, year):
        print 'getIMDBIDmovie'
        imdbid = 0
        try:
            self.log("metahander")
            self.metaget = metahandlers.MetaData(preparezip=False)
            imdbid = (self.metaget.get_meta('movie', showtitle)['imdb_id'])
            if not imdbid or imdbid == 'Empty':
                imdbid = 0
        except Exception,e:
            imdbid = 0
            pass

        if imdbid == 0:
            try:
                self.log("tmdb")
                movieInfo = (self.tmdbAPI.getMovie(showtitle, year))
                imdbid = (movieInfo['imdb_id'])
                if not imdbid or imdbid == 'Empty':
                    imdbid = 0
            except Exception,e:
                imdbid = 0
                pass
                
        print imdbid
        return imdbid
        
    
    def getTVDBIDbyZap2it(self, dd_progid):
        print 'getTVDBIDbyZap2it'
        tvdbid = 0
        
        try:
            tvdbid = self.tvdbAPI.getIdByZap2it(dd_progid)
            if not tvdbid or tvdbid == 'Empty':
                tvdbid = 0
        except Exception,e:
            pass

        print tvdbid
        return tvdbid
        
        
    def getTVINFObySubtitle(self, title, subtitle):
        print 'getTVINFObySubtitle'
        
        try:
            episode = self.t[title].search(subtitle, key = 'episodename')
            # Output example: [<Episode 01x01 - My First Day>]
            episode = str(episode[0])
            episode = episode.split('x')
            seasonNumber = int(episode[0].split('Episode ')[1])
            episodeNumber = int(episode[1].split(' -')[0])
            episodeName = str(episode[1]).split('- ')[1].replace('>','')
            if not episodeName or episodeName == 'Empty':
                episodeName = ''
            if not seasonNumber or seasonNumber == 'Empty':
                seasonNumber = 0    
            if not episodeNumber or episodeNumber == 'Empty':
                episodeNumber = 0
        except Exception,e:
            episodeName = ''
            seasonNumber = 0
            episodeNumber = 0
            pass
            
        return episodeName, seasonNumber, episodeNumber

        
    def getTVINFObySE(self, title, seasonNumber, episodeNumber):
        print 'getTVINFObySE'
        
        try:
            episode = self.t[title][seasonNumber][episodeNumber]
            episodeName = str(episode['episodename'])
            episodeDesc = str(episode['overview'])
            episodeGenre = str(self.t[title]['genre'])
            # Output ex. Comedy|Talk Show|
            episodeGenre = str(episodeGenre)
            try:
                episodeGenre = str(episodeGenre.split('|')[1])
            except:
                pass
        except Exception,e:
            episode = ''
            episodeName = ''
            episodeDesc = ''
            episodeGenre = 'Unknown'
            pass
        
        return episodeName, episodeDesc, episodeGenre
        
        
    def getMovieINFObyTitle(self, title, year):
        print 'getMovieINFObyTitle'
        imdbid = 0
        
        try:
            movieInfo = self.tmdbAPI.getMovie((title), year)
            imdbid = movieInfo['imdb_id']
            try:
                plot = str(movieInfo['overview'])
            except:
                plot = ''
                pass
            try:
                tagline = str(movieInfo['tagline'])
            except:
                tagline = ''
                pass
            try:
                genre = str(movieInfo['genres'][0])
                genre = str((genre.split("u'")[3])).replace("'}",'')
            except:
                genre = 'Unknown'
                pass
                
            if not imdbid or imdbid == 'None' or imdbid == 'Empty':
                imdbid = 0
                
        except Exception,e:
            plot = ''
            tagline = ''
            genre = 'Unknown'
            pass

        return imdbid, plot, tagline, genre
           
    
    #return plugin query, not tmpstr
    def PluginQuery(self, path): 
        self.log("PluginQuery") 
        FleType = 'video'
        json_query = uni('{"jsonrpc": "2.0", "method": "Files.GetDirectory", "params": {"directory": "%s", "media": "%s", "properties":["title","year","mpaa","imdbnumber","description","season","episode","playcount","genre","duration","runtime","showtitle","album","artist","plot","plotoutline","tagline"]}, "id": 1}' % (self.escapeDirJSON(path), FleType))
        json_folder_detail = self.sendJSON(json_query)
        file_detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)
        return file_detail
    
    
    #Parse Plugin, return essential information. Not tmpstr
    def PluginInfo(self, path):
        print 'PluginInfo'
        json_query = uni('{"jsonrpc":"2.0","method":"Files.GetDirectory","params":{"directory":"%s","properties":["genre","runtime","description"]},"id":1}' % ( (path),))
        json_folder_detail = self.sendJSON(json_query)
        file_detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)
        Detail = ''
        DetailLST = []
        PluginName = os.path.split(path)[0]

        #run through each result in json return
        for f in (file_detail):
            filetype = re.search('"filetype" *: *"(.*?)"', f)
            label = re.search('"label" *: *"(.*?)"', f)
            genre = re.search('"genre" *: *"(.*?)"', f)
            runtime = re.search('"runtime" *: *([0-9]*?),', f)
            description = re.search('"description" *: *"(.*?)"', f)
            file = re.search('"file" *: *"(.*?)"', f)

            #if core values have info, proceed
            if filetype and file and label:
                filetype = filetype.group(1)
                title = (label.group(1)).replace(',',' ')
                file = file.group(1)

                try:
                    genre = genre.group(1)
                except:
                    genre = 'Unknown'
                    pass

                if genre == '':
                    genre = 'Unknown'

                try:
                    runtime = runtime.group(1)
                except:
                    runtime = 0
                    pass

                if runtime == 0 or runtime == '':
                    runtime = 1800

                try:
                    description = (description.group(1)).replace(',',' ')
                except:
                    description = PluginName
                    pass

                if description == '':
                    description = PluginName

                if title != '':
                    Detail = ((filetype + ',' + title + ',' + genre + ',' + str(runtime) + ',' + description + ',' + file)).replace(',,',',')
                    DetailLST.append(Detail)

        return DetailLST
    
 
    #recursively walk through plugin directories, return tmpstr of all files found.
    def PluginWalk(self, path, excludeLST, limit, channel, xType, FleType='video'):
        print "PluginWalk"
        file_detail_CHK = []
        dirlimit = int(limit * 2)
        tmpstr = ''
        LiveID = 'tvshow|0|0|False|1|NR|'
        fileList = []
        dirs = []
        Managed = False
        PluginPath = str(os.path.split(path)[0])
        PluginName = PluginPath.replace('plugin://plugin.video.','').replace('plugin://plugin.program.','')

        json_query = uni('{"jsonrpc": "2.0", "method": "Files.GetDirectory", "params": {"directory": "%s", "media": "%s", "properties":["title","year","mpaa","imdbnumber","description","season","episode","playcount","genre","duration","runtime","showtitle","album","artist","plot","plotoutline","tagline"]}, "id": 1}' % ((path), FleType))
        json_folder_detail = self.sendJSON(json_query)
        file_detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)

        # #Plugin listitems return parent list during error, catch repeat list and end loops.
        # if file_detail_CHK == file_detail:
            # return
        # else:
            # file_detail_CHK = file_detail
            
        try:
            if xType == '':
                xName = xType
                PlugCHK = xType
            elif xType.lower() == 'playon':
                xName = (path.split('/')[3]).split('-')[0]
                PlugCHK = xType
            else:
                xName = PluginName
                PlugCHK = PluginPath.replace('plugin://','')

            #run through each result in json return
            for f in (file_detail):
                if self.threadPause() == False:
                    del fileList[:]
                    break

                istvshow = False
                f = self.runActions(RULES_ACTION_JSON, channel, f)
                durations = re.search('"duration" *: *([0-9]*?),', f)
                runtimes = re.search('"runtime" *: *([0-9]*?),', f)
                filetypes = re.search('"filetype" *: *"(.*?)"', f)
                labels = re.search('"label" *: *"(.*?)"', f)
                files = re.search('"file" *: *"(.*?)"', f)

                #if core variables have info proceed
                if filetypes and labels and files:
                    filetype = filetypes.group(1)
                    file = files.group(1)
                    label = labels.group(1)
                    label = self.CleanLabels(label)
                    
                    if label.lower() not in excludeLST:
                        print 'PluginWalk, ' + ascii(label) + ' not in excludeLST'

                        if filetype == 'directory':
                            print 'PluginWalk, directory'

                            #try to speed up parsing by not over searching directories when media limit is low
                            if self.filecount < limit and self.dircount < dirlimit:

                                if file[0:4] != 'upnp':
                                    #if no return, try unquote
                                    if not self.PluginInfo(file):
                                        print 'unquote'
                                        file = unquote(file).replace('",return)','')
                                        #remove unwanted reference to super.favorites plugin
                                        try:
                                            file = (file.split('ActivateWindow(10025,"')[1])
                                        except:
                                            pass

                                if self.background == False:
                                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "Building " + xType + ", parsing " + (xName), "found " + label)

                                dirs.append(file)
                                self.dircount += 1
                                print "PluginWalk, dircount = " + str(self.dircount) +'/'+ str(dirlimit)
                            else:
                                self.dircount = 0
                                break

                        elif filetype == 'file':
                            print 'PluginWalk, file'

                            if self.filecount < limit:


                                #Remove PlayMedia to keep link from launching
                                try:
                                    file = ((file.split('PlayMedia%28%22'))[1]).replace('%22%29','')
                                except:
                                    try:
                                        file = ((file.split('PlayMedia("'))[1]).replace('")','')
                                    except:
                                        pass

                                if file.startswith('plugin%3A%2F%2F'):
                                    print 'unquote'
                                    file = unquote(file).replace('",return)','')

                                # If music duration returned, else 0
                                try:
                                    dur = int(durations.group(1))
                                except Exception,e:
                                    dur = 0

                                if dur == 0:
                                    try:
                                        dur = int(runtimes.group(1))
                                    except Exception,e:
                                        dur = 3600

                                    if not runtimes or dur == 0:
                                        dur = 3600

                                #correct playon default duration
                                if dur == 18000:
                                    dur = 3600

                                print 'PluginWalk, dur = ' + str(dur)

                                if dur > 0:
                                    self.filecount += 1
                                    print "PluginWalk, filecount = " + str(self.filecount) +'/'+ str(limit)

                                    tmpstr = str(dur) + ','
                                    labels = re.search('"label" *: *"(.*?)"', f)
                                    titles = re.search('"title" *: *"(.*?)"', f)
                                    showtitles = re.search('"showtitle" *: *"(.*?)"', f)
                                    plots = re.search('"plot" *: *"(.*?)",', f)
                                    plotoutlines = re.search('"plotoutline" *: *"(.*?)",', f)
                                    years = re.search('"year" *: *([0-9]*?) *(.*?)', f)
                                    genres = re.search('"genre" *: *\[(.*?)\]', f)
                                    playcounts = re.search('"playcount" *: *([0-9]*?),', f)
                                    imdbnumbers = re.search('"imdbnumber" *: *"(.*?)"', f)
                                    ratings = re.search('"mpaa" *: *"(.*?)"', f)
                                    descriptions = re.search('"description" *: *"(.*?)"', f)
                                    episodes = re.search('"episode" *: *(.*?),', f)

                                    if (episodes != None and episodes.group(1) != '-1') and showtitles != None and len(showtitles.group(1)) > 0:
                                        type = 'tvshow'
                                        dbids = re.search('"tvshowid" *: *([0-9]*?),', f)
                                        FolderName = showtitles.group(1)
                                    else:
                                        type = 'movie'
                                        dbids = re.search('"movieid" *: *([0-9]*?),', f)
                                        FolderName = label

                                    if self.background == False:
                                        if self.filecount == 1:
                                            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding " + xType + ", parsing " + xName, "added " + str(self.filecount) + " entry")
                                        else:
                                            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "adding " + xType + ", parsing " + xName, "added " + str(self.filecount) + " entries")

                                    if years == None or len(years.group(1)) == 0:
                                        try:
                                            year = int(((showtitles.group(1)).split(' ('))[1].replace(')',''))
                                        except Exception,e:
                                            try:
                                                year = int(((labels.group(1)).split(' ('))[1].replace(')',''))
                                            except:
                                                year = 0
                                                pass
                                    else:
                                        year = 0

                                    if genres != None and len(genres.group(1)) > 0:
                                        genre = ((genres.group(1).split(',')[0]).replace('"',''))
                                    else:
                                        genre = 'Unknown'

                                    if playcounts != None and len(playcounts.group(1)) > 0:
                                        playcount = playcounts.group(1)
                                    else:
                                        playcount = 1

                                    if ratings != None and len(ratings.group(1)) > 0:
                                        rating = self.cleanRating(ratings.group(1))
                                        if type == 'movie':
                                            rating = rating[0:5]
                                            try:
                                                rating = rating.split(' ')[0]
                                            except:
                                                pass
                                    else:
                                        rating = 'NR'

                                    if imdbnumbers != None and len(imdbnumbers.group(1)) > 0:
                                        imdbnumber = imdbnumbers.group(1)
                                    else:
                                        imdbnumber = 0

                                    if dbids != None and len(dbids.group(1)) > 0:
                                        dbid = dbids.group(1)
                                    else:
                                        dbid = 0

                                    if plots != None and len(plots.group(1)) > 0:
                                        theplot = (plots.group(1)).replace('\\','').replace('\n','')
                                    elif descriptions != None and len(descriptions.group(1)) > 0:
                                        theplot = (descriptions.group(1)).replace('\\','').replace('\n','')
                                    else:
                                        theplot = (titles.group(1)).replace('\\','').replace('\n','')

                                    try:
                                        theplot = (self.trim(theplot, 350, '...'))
                                    except Exception,e:
                                        self.log("Plot Trim failed" + str(e))
                                        theplot = (theplot[:350])

                                    #remove // because interferes with playlist split.
                                    theplot = self.CleanLabels(theplot)

                                    # This is a TV show
                                    if (episodes != None and episodes.group(1) != '-1') and showtitles != None and len(showtitles.group(1)) > 0:
                                        seasons = re.search('"season" *: *(.*?),', f)
                                        episodes = re.search('"episode" *: *(.*?),', f)
                                        swtitle = (labels.group(1)).replace('\\','')

                                        try:
                                            seasonval = int(seasons.group(1))
                                            epval = int(episodes.group(1))
                                        except:
                                            seasonval = -1
                                            epval = -1
                                            pass
             
                                        if seasonval > 0 and epval != -1:
                                            try:
                                                eptitles = swtitle.split(' - ')[1]
                                            except:
                                                try:
                                                    eptitles = swtitle.split(' . ')[1]
                                                except:
                                                    eptitles = swtitle
                                                    pass
                                        else:
                                            #no season, episode meta. try to extract from swtitle
                                            try:
                                                #S01E01 - eptitle or s01e01 - eptitle
                                                SEinfo = (swtitle.split(' - ')[0]).replace('S','s').replace('E','e')
                                                seasonval = SEinfo.split('e')[0].replace('s','')
                                                epval = SEinfo.split('e')[1]
                                                eptitles = (swtitle.split('- ', 1)[1])
                                            except:
                                                try:
                                                    #2x01 - eptitle or #2X01 - eptitle
                                                    SEinfo = (swtitle.split(' -')[0]).replace('X','x')
                                                    seasonval = SEinfo.split('x')[0]
                                                    epval = SEinfo.split('x')[1]
                                                    eptitles = (swtitle.split('- ', 1)[1])
                                                except:
                                                    try:
                                                        #2x01 . eptitle or #2X01 . eptitle
                                                        SEinfo = (swtitle.split(' . ',1)[0]).replace('X','x')
                                                        seasonval = SEinfo.split('x')[0]
                                                        epval = SEinfo.split('x')[1]
                                                        eptitles = (swtitle.split(' . ', 1)[1])
                                                    except:
                                                        eptitles = swtitle
                                                        seasonval = -1
                                                        epval = -1
                                                        pass

                                        if seasonval > 0 and epval > 0:
                                            swtitle = (('0' if seasonval < 10 else '') + str(seasonval) + 'x' + ('0' if epval < 10 else '') + str(epval) + ' - ' + (eptitles)).replace('  ',' ')
                                        else:
                                            swtitle = swtitle.replace(' . ',' - ')

                                        showtitle = (showtitles.group(1))
                                        showtitle = self.CleanLabels(showtitle)
                                        
                                        if REAL_SETTINGS.getSetting('EnhancedGuideData') == 'true':
                                            print 'EnhancedGuideData'

                                            if PlugCHK in DYNAMIC_PLUGIN_TV:
                                                print 'DYNAMIC_PLUGIN_TV'

                                                if imdbnumber == 0:
                                                    imdbnumber = self.getTVDBID(showtitle, year)

                                                if genre == 'Unknown':
                                                    genre = (self.getGenre(type, showtitle, year))

                                                if rating == 'NR':
                                                    rating = (self.getRating(type, showtitle, year, imdbnumber))
                                                    rating = self.cleanRating(rating)

                                        GenreLiveID = [genre, type, imdbnumber, dbid, Managed, 1, rating]
                                        genre, LiveID = self.packGenreLiveID(GenreLiveID)
                                        
                                        swtitle = self.CleanLabels(swtitle)
                                        theplot = self.CleanLabels(theplot)
                                        tmpstr += showtitle + "//" + swtitle + "//" + theplot + "//" + genre + "////" + LiveID
                                        istvshow = True

                                    else:

                                        if labels:
                                            label = (labels.group(1))
                                            label = self.CleanLabels(label)
                                            
                                        if titles:
                                            title = (titles.group(1))
                                            title = self.CleanLabels(title)

                                        tmpstr += label + "//"

                                        album = re.search('"album" *: *"(.*?)"', f)

                                        # This is a movie
                                        if not album or len(album.group(1)) == 0:
                                            taglines = re.search('"tagline" *: *"(.*?)"', f)

                                            if taglines != None and len(taglines.group(1)) > 0:
                                                tagline = (taglines.group(1))
                                                tagline = self.CleanLabels(tagline)
                                                tmpstr += tagline
                                            else:
                                                tmpstr += 'PluginTV'

                                            if REAL_SETTINGS.getSetting('EnhancedGuideData') == 'true':
                                                print 'EnhancedGuideData'
                                                
                                                if PlugCHK in DYNAMIC_PLUGIN_MOVIE:
                                                    print 'DYNAMIC_PLUGIN_MOVIE'

                                                    try:
                                                        showtitle = label.split(' (')[0]
                                                        year = (label.split(' (')[1]).replace(')','')
                                                    except:
                                                        showtitle = label
                                                        year = ''
                                                        pass

                                                    try:
                                                        showtitle = showtitle.split('. ')[1]
                                                    except:
                                                        pass

                                                    if imdbnumber == 0:
                                                        imdbnumber = self.getIMDBIDmovie(showtitle, year)

                                                    if genre == 'Unknown':
                                                        genre = (self.getGenre(type, showtitle, year))

                                                    if rating == 'NR':
                                                        rating = (self.getRating(type, showtitle, year, imdbnumber))
                                                        rating = self.cleanRating(rating)

                                            GenreLiveID = [genre, type, imdbnumber, dbid, Managed, 1, rating]
                                            genre, LiveID = self.packGenreLiveID(GenreLiveID)
                                            
                                            theplot = self.CleanLabels(theplot)
                                            tmpstr += "//" + theplot + "//" + genre + "////" + (LiveID)

                                        else: #Music
                                            LiveID = 'music|0|0|False|1|NR|'
                                            artist = re.search('"artist" *: *"(.*?)"', f)
                                            
                                            if album != None and len(album.group(1)) > 0:
                                                albumTitle = album.group(1)
                                            else:
                                                albumTitle = label.group(1)
                                                
                                            if artist != None and len(artist.group(1)) > 0:
                                                artistTitle = album.group(1)
                                            else:
                                                artistTitle = ''
                                                
                                            albumTitle = self.CleanLabels(albumTitle)
                                            artistTitle = self.CleanLabels(artistTitle)
                                            
                                            tmpstr += albumTitle + "//" + artistTitle + "//" + 'Music' + "////" + LiveID

                                    file = file.replace('plugin://plugin.video.youtube/?action=play_video&videoid=', self.youtube_ok)
                                    tmpstr = tmpstr.replace("\\n", " ").replace("\\r", " ").replace("\\\"", "\"")
                                    tmpstr = tmpstr + '\n' + file.replace("\\\\", "\\")

                                    if self.channels[channel - 1].mode & MODE_ORDERAIRDATE > 0:
                                        seasoneplist.append([seasonval, epval, tmpstr])
                                    else:
                                        fileList.append(tmpstr)
                            else:
                                print 'PluginWalk, filecount break'
                                self.filecount = 0
                                break

            for item in dirs:
                print 'PluginWalk, recursive directory walk'

                if self.filecount >= limit:
                    print 'PluginWalk, recursive filecount break'
                    break

                #recursively scan all subfolders
                fileList += self.PluginWalk(item, excludeLST, limit, channel, xType, FleType)

                if self.channels[channel - 1].mode & MODE_ORDERAIRDATE > 0:
                    seasoneplist.sort(key=lambda seep: seep[1])
                    seasoneplist.sort(key=lambda seep: seep[0])


                    for seepitem in seasoneplist:
                        fileList.append(seepitem[2])
        except:
            pass

        self.log("PluginWalk return")
        return fileList
    
    
    def BuildPluginFileList(self, setting1, setting2, setting3, setting4, channel):
        xbmc.log("BuildPluginFileList Cache")
        if Cache_Enabled == True:  
            try:
                result = pluginTV.cacheFunction(self.BuildPluginFileList_NEW, setting1, setting2, setting3, setting4, channel)
            except:
                result = self.BuildPluginFileList_NEW(setting1, setting2, setting3, setting4, channel)
                pass
        else:
            result = self.BuildPluginFileList_NEW(setting1, setting2, setting3, setting4, channel)
        if not result:
            result = []
        return result  
        

    def BuildPluginFileList_NEW(self, setting1, setting2, setting3, setting4, channel):
        print "BuildPluginFileList"
        showList = []
        DetailLST = []
        DetailLST_CHK = []
        self.dircount = 0
        self.filecount = 0

        try:
            Directs = (setting1.split('/')) # split folders
            Directs = ([x for x in Directs if x != '']) # remove empty elements
            plugins = Directs[1] # element 1 in split is plugin name
            Directs = Directs[2:] # slice two unwanted elements. ie (plugin:, plugin name)
            plugin = 'plugin://' + plugins
            PluginName = plugins.replace('plugin.video.','').replace('plugin.program.','')
        except:
            Directs = []
            pass

        try:
            excludeLST = setting2.split(',')
            excludeLST = ([x.lower() for x in excludeLST if x != '']) # remove empty elements
        except:
            excludeLST = []
            pass
            
        #filter out unwanted folders
        excludeLST += ['back','previous','home','create new super folder','explore favourites','explore  favourites','explore xbmc favourites','explore kodi favourites','isearch','search','clips','seasons','trailers']
        
        if self.background == False:
            self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "Building PluginTV", 'parsing ' + (PluginName))
            
        if setting3 == '':
            limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
            if limit == 0 or limit > 200:
                limit = 200
            elif limit < 25:
                limit = 25
            self.log("BuildPluginFileList, Using Global Parse-limit " + str(limit))
        else:
            limit = int(setting3)
            self.log("BuildPluginFileList, Overriding Global Parse-limit to " + str(limit))

        Match = True
        while Match:

            DetailLST = self.PluginInfo(plugin)

            #Plugin listitems return parent list during error, catch repeat list and end loops.
            if DetailLST_CHK == DetailLST:
                break
            else:
                DetailLST_CHK = DetailLST

            #end while when no more directories to walk
            if len(Directs) <= 1:
                Match = False
                
            try:
                for i in range(len(DetailLST)):
                
                    if self.background == False:
                        self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "Building PluginTV, parsing " + (PluginName), str(Directs[0]))
                        
                    Detail = (DetailLST[i]).split(',')
                    filetype = Detail[0]
                    title = Detail[1]
                    title = self.CleanLabels(title)
                    genre = Detail[2]
                    dur = Detail[3]
                    description = Detail[4]
                    file = Detail[5]
                    
                    if title.lower() not in excludeLST and title != '':
                        if filetype == 'directory':
                            CurDirect = self.CleanLabels(Directs[0])
                            if CurDirect.lower() == title.lower():
                                print 'directory match'
                                Directs.pop(0) #remove old directory, search next element
                                plugin = file
                                break
            except Exception,e:
                pass
                
        #all directories found, walk final folder
        if len(Directs) == 0:              
            showList = self.PluginWalk(plugin, excludeLST, limit, channel, 'PluginTV', 'video')
                
        return showList    
           
    
    def BuildPlayonFileList(self, setting1, setting2, setting3, setting4, channel):
        xbmc.log("BuildPlayonFileList Cache")
        if Cache_Enabled == True:
            try:
                result = playonTV.cacheFunction(self.BuildPlayonFileList_NEW, setting1, setting2, setting3, setting4, channel)
            except:
                result = self.BuildPlayonFileList_NEW(setting1, setting2, setting3, setting4, channel)
                pass
        else:
            result = self.BuildPlayonFileList_NEW(setting1, setting2, setting3, setting4, channel)
        if not result:
            result = []
        return result  
        
 
    def BuildPlayonFileList_NEW(self, setting1, setting2, setting3, setting4, channel):
        print ("BuildPlayonFileList")
        showList = []
        DetailLST = []
        DetailLST_CHK = []
        self.dircount = 0
        self.filecount = 0
        upnpID = self.playon_ok

        if upnpID != False:

            try:
                Directs = (setting1.split('/')) # split folders
                Directs = ([x for x in Directs if x != '']) # remove empty elements
                PluginName = Directs[0]
            except:
                Directs = []
                PluginName = setting1
                pass

            try:
                excludeLST = setting2.split(',')
                excludeLST = ([x.lower() for x in excludeLST if x != '']) # remove empty elements
            except:
                excludeLST = []
                pass
                
            #filter out unwanted folders
            excludeLST += ['back','previous','home','create new super folder','explore favourites','explore  favourites','explore xbmc favourites','explore kodi favourites','isearch','search','clips','seasons','trailers']
                    
            if self.background == False:
                self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "Building PlayOn", 'parsing ' + str(PluginName))
                
            if setting3 == '':
                limit = MEDIA_LIMIT[int(REAL_SETTINGS.getSetting('MEDIA_LIMIT'))]
                if limit == 0 or limit > 200:
                    limit = 200
                elif limit < 25:
                    limit = 25
                self.log("BuildPlayonFileList, Using Global Parse-limit " + str(limit))
            else:
                limit = int(setting3)
                self.log("BuildPlayonFileList, Overriding Global Parse-limit to " + str(limit))

            Match = True
            while Match:

                DetailLST = self.PluginInfo(upnpID)

                #Plugin listitems return parent list during error, catch repeat list and end loops.
                if DetailLST_CHK == DetailLST:
                    break
                else:
                    DetailLST_CHK = DetailLST

                #end while when no more directories to walk
                if len(Directs) <= 1:
                    Match = False
                
                try:
                    for i in range(len(DetailLST)):
                        Detail = (DetailLST[i]).split(',')
                        filetype = Detail[0]
                        title = Detail[1]
                        genre = Detail[2]
                        dur = Detail[3]
                        description = Detail[4]
                        file = Detail[5]

                        if title.lower() not in excludeLST and title != '':
                            if filetype == 'directory':
                                if Directs[0].lower() == title.lower():
                                    print 'directory match'
                                    Directs.pop(0) #remove old directory, search next element
                                    upnpID = file
                                    break
                except Exception,e:
                    pass    
                    
            #all directories found, walk final folder
            if len(Directs) == 0:
                showList = self.PluginWalk(upnpID, excludeLST, limit, channel, 'PlayOn', 'video')

            return showList
        
        
    # Run rules for a channel
    def runActions(self, action, channel, parameter):
        self.log("runActions " + str(action) + " on channel " + str(channel))
        if channel < 1:
            return

        self.runningActionChannel = channel
        index = 0

        for rule in self.channels[channel - 1].ruleList:
            if rule.actions & action > 0:
                self.runningActionId = index

                if self.background == False:
                    self.updateDialog.update(self.updateDialogProgress, "Updating channel " + str(self.settingChannel), "processing rule " + str(index + 1), '')

                parameter = rule.runAction(action, self, parameter)

            index += 1

        self.runningActionChannel = 0
        self.runningActionId = 0
        return parameter


    def threadPause(self):
        if threading.activeCount() > 1:
            while self.threadPaused == True and self.myOverlay.isExiting == False:
                time.sleep(self.sleepTime)

            # This will fail when using config.py
            try:
                if self.myOverlay.isExiting == True:
                    self.log("IsExiting")
                    return False
            except Exception,e:
                pass
                
        return True


    def escapeDirJSON(self, dir_name):
        mydir = uni(dir_name)

        if (mydir.find(":")):
            mydir = mydir.replace("\\", "\\\\")
        return mydir


    def getSmartPlaylistType(self, dom):
        self.log('getSmartPlaylistType')

        try:
            pltype = dom.getElementsByTagName('smartplaylist')
            return pltype[0].attributes['type'].value
        except Exception,e:
            self.log("Unable to get the playlist type.", xbmc.LOGERROR)
            return ''
            
        
    def splitall(self, path):
        self.log("splitall")
        allparts = []
        while 1:
            parts = os.path.split(path)
            if parts[0] == path:  # sentinel for absolute paths
                allparts.insert(0, parts[0])
                break
            elif parts[1] == path: # sentinel for relative paths
                allparts.insert(0, parts[1])
                break
            else:
                path = parts[0]
                allparts.insert(0, parts[1])
        return allparts
        
        
    def remDupes(self, filelist, idfun=None):
        self.log("remDupes")   
        # order preserving
        if idfun is None:
           def idfun(x): return x
        seen = {}
        result = []
        for item in filelist:
           marker = idfun(item)
           # in old Python versions:
           # if seen.has_key(marker)
           # but in new ones:
           if marker in seen: continue
           seen[marker] = 1
           result.append(item)
        return result

        
    def findZap2itID(self, CHname, filename):
        self.log("findZap2itID")   
        if filename.startswith('http'):
            json_folder_detail = str(xmltv.read_channels(Open_URL(filename)))
        else:
            json_folder_detail = str(xmltv.read_channels(FileAccess.open(filename, 'r')))
        
        file_detail = re.compile( "{(.*?)}", re.DOTALL ).findall(json_folder_detail)

        try:
            CHnum = CHname.split(' ')[0]
            CHname = CHname.split(' ')[1]
        except:
            pass

        CHname = CHname.replace('-DT','DT').replace(' DT','DT').replace('DT','').replace('-HD','HD').replace(' HD','HD').replace('HD','').replace('-SD','SD').replace(' SD','SD').replace('SD','')
        matchLST = [CHname.upper(), 'W'+CHname.upper(), CHnum+' '+CHname.upper(), CHnum+' W'+CHname.upper()]
        print matchLST

        for f in (file_detail):
            found = False
            match = re.search("'display-name' *: *\[(.*?)\]", f)
            id = re.search("'id': (.+)", f)
            
            if match != None and len(match.group(1)) > 0 and id != None and len(id.group(1)) > 0:
                dnames = match.group(1)
                CHid = (id.group(1)).replace("'",'')
                dnames = (dnames.replace("('",'').replace("', '')",'')).split(', ')

                for i in range(len(dnames)):
                    dname = dnames[i].replace('-DT','DT').replace(' DT','DT').replace('DT','').replace('-HD','HD').replace(' HD','HD').replace('HD','').replace('-SD','SD').replace(' SD','SD').replace('SD','')

                    if dname.upper() in matchLST: 
                        self.log("findZap2itID, Match Found: " + str(CHname.upper()) +' == '+ str(dname.upper()) + str(CHid))  
                        found = True
                        break

            if found == True:
                break
            else:
                CHid = '0'

        return CHname, CHid
        
        
    def SyncUSTVnow(self, silent=False, force=False):
        self.log('SyncUSTVnow')
        now  = datetime.datetime.today()
        USTVnow = self.plugin_ok('plugin.video.ustvnow')
        
        if USTVnow == True:
            
            try:
                SyncUSTVnow_NextRun = REAL_SETTINGS.getSetting('SyncUSTVnow_NextRun')
                SyncUSTVnow_NextRun = SyncUSTVnow_NextRun.split('.')[0]
                SyncUSTVnow_NextRun = datetime.datetime.strptime(SyncUSTVnow_NextRun, '%Y-%m-%d %H:%M:%S')
            except:
                SyncUSTVnow_NextRun = now
                pass
            
            #Force Download
            if force == True:
                self.log('SyncUSTVnow, Force Run')
                SyncUSTVnow_NextRun = now
            
            #Force Download - If missing
            if not FileAccess.exists(USTVnowXML):
                SyncUSTVnow_NextRun = now
                
            if now >= SyncUSTVnow_NextRun: 

                if NOTIFY == 'true':
                    xbmc.executebuiltin("Notification( %s, %s, %d, %s)" % ("PseudoTV Live","USTVnow XMLTV Updating", 4000, THUMB) )
                    
                self.log('SyncUSTVnow, Updating XMLTV')
                url = 'http://copy.com/D4juDEUQw9eBj2q3/ustvnow.xml'
                url_bak = ''
                         
                if FileAccess.exists(USTVnowXML):
                    try:
                        xbmcvfs.delete(USTVnowXML)
                    except:
                        pass           
                      
                try: 
                    f = Open_URL(url)
                    USxmltv = url
                    xbmc.log("ustvnow, INFO: URL Connected...")
                except urllib2.URLError as e:
                    f = Open_URL(url_bak)
                    USxmltv = url_bak
                    xbmc.log("ustvnow, INFO: URL_BAK Connected...")
                except urllib2.URLError as e:
                    pass
                    
                SyncUSTVnow_NextRun = (SyncUSTVnow_NextRun + datetime.timedelta(hours=48))
                REAL_SETTINGS.setSetting("SyncUSTVnow_NextRun",str(SyncUSTVnow_NextRun))
                if silent == True:
                    download_silent(USxmltv, USTVnowXML)
                else:
                    download(USxmltv, USTVnowXML)
                return True
            

    def SyncSSTV(self, silent=False, force=False):
        self.log('SyncSSTV')
        now  = datetime.datetime.today()
        SSTV = self.plugin_ok('plugin.video.mystreamstv.beta')
        if SSTV == True:
            
            try:
                SyncSSTV_NextRun = REAL_SETTINGS.getSetting('SyncSSTV_NextRun')
                SyncSSTV_NextRun = SyncSSTV_NextRun.split('.')[0]
                SyncSSTV_NextRun = datetime.datetime.strptime(SyncSSTV_NextRun, '%Y-%m-%d %H:%M:%S')
            except:
                SyncSSTV_NextRun = now
                pass
            
            #Force Download
            if force == True:
                SyncSSTV_NextRun = now
            
            #Force Download - If missing
            if not FileAccess.exists(SSTVXML):
                SyncSSTV_NextRun = now
                
            if now >= SyncSSTV_NextRun: 

                if NOTIFY == 'true':
                    xbmc.executebuiltin("Notification( %s, %s, %d, %s)" % ("PseudoTV Live","SmoothStream XMLTV Updating", 4000, THUMB) )
                    
                url = 'http://copy.com/g1Tjx7BvedETDg7f/SStream.xml'
                # url_bak = 'http://smoothstreams.tv/schedule/feed.xml'
                # url_bak = 'http://smoothstreams.tv/schedule/feed.json'
                         
                if FileAccess.exists(SSTVXML):
                    try:
                        xbmcvfs.delete(SSTVXML)
                    except:
                        pass           
            
                try: 
                    f = Open_URL(url)
                    SSxmltv = url
                    xbmc.log("sstv, INFO: URL Connected...")
                except urllib2.URLError as e:
                    f = Open_URL(url_bak)
                    SSxmltv = url_bak
                    xbmc.log("sstv, INFO: URL_BAK Connected...")
                except urllib2.URLError as e:
                    pass
                        
                SyncSSTV_NextRun = (SyncSSTV_NextRun + datetime.timedelta(hours=48))
                REAL_SETTINGS.setSetting("SyncSSTV_NextRun",str(SyncSSTV_NextRun))
                if silent == True:
                    download_silent(SSxmltv, SSTVXML)
                else:
                    download(SSxmltv, SSTVXML)
                return True
        
        
    def SyncFTV(self, silent=False, force=False):
        self.log('SyncFTV')
        now  = datetime.datetime.today()
        FTV = self.plugin_ok('plugin.video.F.T.V') 
        if FTV == True:
            
            try:
                SyncFTV_NextRun = REAL_SETTINGS.getSetting('SyncFTV_NextRun')
                SyncFTV_NextRun = SyncFTV_NextRun.split('.')[0]
                SyncFTV_NextRun = datetime.datetime.strptime(SyncFTV_NextRun, '%Y-%m-%d %H:%M:%S')
            except:
                SyncFTV_NextRun = now
                pass
            
            #Force Download
            if force == True:
                SyncFTV_NextRun = now
            
            #Force Download - If missing
            if not FileAccess.exists(FTVXML):
                SyncFTV_NextRun = now
                
            if now >= SyncFTV_NextRun: 

                if NOTIFY == 'true':
                    xbmc.executebuiltin("Notification( %s, %s, %d, %s)" % ("PseudoTV Live","F.T.V XMLTV Updating", 4000, THUMB) )
                    
                url = 'http://copy.com/hxg9bYKzVTlOPzi4/ftvguide.xml'
                url_bak = 'http://users17.jabry.com/PTVL1/db/xmltv/ftvguide.xml'
                         
                if FileAccess.exists(FTVXML):
                    try:
                        xbmcvfs.delete(FTVXML)
                    except:
                        pass           
                try: 
                    f = Open_URL(url)
                    FTVxmltv = url
                    xbmc.log("ftvguide, INFO: URL Connected...")
                except urllib2.URLError as e:
                    f = Open_URL(url_bak)
                    FTVxmltv = url_bak
                    xbmc.log("ftvguide, INFO: URL_BAK Connected...")
                except urllib2.URLError as e:
                    pass
            
                SyncFTV_NextRun = (SyncFTV_NextRun + datetime.timedelta(hours=48))
                REAL_SETTINGS.setSetting("SyncFTV_NextRun",str(SyncFTV_NextRun))
                if silent == True:
                    download_silent(FTVxmltv, FTVXML)
                else:
                    download(FTVxmltv, FTVXML)
                return True
             
 
    def IPTVtuning(self, url):
        IPTVList = []
        IPTVList = IPTVtuning(url)
        return IPTVList
 
 
    def LSTVtuning(self, url):
        LSTVList = []
        LSTVList = LSTVtuning(url)
        return LSTVList
        
        
    def NaviXtuning(self, url):
        NaviXlist = []
        NaviXlist = NaviXtuning(url)
        return NaviXlist

        
    def CleanLabels(self, label):
        #add regex wildcard to catch all colors todo
        label = (label.upper()).replace('[B]','').replace('[/B]','').replace('[/COLOR]','').replace('[COLOR=BLUE]','').replace('[COLOR=CYAN]','').replace('[COLOR=RED]','').replace('[COLOR=GREEB]','').replace('[COLOR=YELLOW]','').replace('[HD]', '').replace('(SUB) ','').replace('(DUB) ','').replace('[CC]','').replace('\\',' ').replace('[COLOR CYAN]','')
        return label.title()
    
    
    def GUISetSwitch(self):
        self.log('GUISetSwitch')
        # fle = xbmc.translatePath("special://profile/guisettings.xml")

        # try:
            # xml = FileAccess.open(fle, "r")
            # dom = parse(xml)
        # except Exception,e:
            # return

        # # try:
        # plname = dom.getElementsByTagName('autoplaynextitem')
        # NextEnabled = (plname[0].childNodes[0].nodeValue.lower() == 'true')
        # REAL_SETTINGS.setSetting("AutoPlayNext",str(NextEnabled))
        
        # if REAL_SETTINGS.getSetting('AutoPlayNext') == "true":
            # plname[0].childNodes[0].nodeValue.lower() = 'true'
        # else:
            # plname[0].childNodes[0].nodeValue.lower() = 'false'
            
        # xml.close()
       
       
    def GrabLogo(self, url, title):
        print 'GrabLogo'
        if REAL_SETTINGS.getSetting('ChannelLogoFolder') != '':
            LogoPath = xbmc.translatePath(REAL_SETTINGS.getSetting('ChannelLogoFolder'))
            LogoFile = os.path.join(LogoPath, title[0:18] + '.png')
            
            if not FileAccess.exists(LogoFile):
                Download_URL(logo, LogoFile)
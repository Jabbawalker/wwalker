#!/usr/bin/python3
# -*- coding: utf8 -*-

import asyncio
import random
import configparser
import os, sys
import signal
import time
import re
import platform
import subprocess
import copy

from enum import Enum
from telethon import TelegramClient, sync, events

MIN_RESPONSE_DELAY = 1
MAX_RESPONSE_DELAY = 6
EXHAUSTED_MODE_DELAY = 120
GIANT_POLL_INTERVAL = (120,180)
INACTIVITY_POLL_TIMEOUT = 180

DEFAULT_HUNGER_TRHESHOLD = 50

PROFILES_DIR = 'profiles'

SIGHUP_AVAILABLE = hasattr(signal, 'SIGHUP')

def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S") + ' ' + msg)


class Intervals:

    def __init__(self):
        self.points = { 0: 0 }

    def add(self,start,value):
        if start is None:
            return
        if not self.points:
            self.points[start] = value
            return
        self.points[start] = value
        for k in sorted(self.points.keys(),reverse = True):
            if k > start:
                del self.points[k]

    def clear(self):
        self.points = {}

    def get(self,pos):
        for k in sorted(self.points.keys(), reverse = True):
            if pos >= k:
                return self.points[k]

        return 0

    def from_spec(self, spec):
        try:
            for item in spec.split(','):
                v = item.split('/')
                if len(v)>2:
                    return 'wrong input. too many slashes'
                if len(v)==1:
                    self.add(0,int(v[0]))
                else:
                    self.add(int(v[1]),int(v[0]))
            return None
        except:
            return 'failed to parse input'

    def str2bool(self,s):
        if s in ['true', '1', 't', 'y', 'yes', 'yeah', 'yup']:
            return True
        elif s in ['false', '0', 'f', 'n', 'no', 'nope']:
            return False
        raise Exception('unexpected boolean spec: ' + s)

    def bool2str(self,b):
        if b:
            return 'y'
        return 'n'

    def from_spec_bool(self, spec):
        try:
            for item in spec.split(','):
                v = item.split('/')
                if len(v)>2:
                    return 'wrong input. too many slashes'
                if len(v)==1:
                    self.add(0,self.str2bool(v[0]))
                else:
                    self.add(int(v[1]),self.str2bool(v[0]))
            return None
        except:
            return 'failed to parse input'

    def to_spec(self):
        if not self.points:
            return ''
        specs = []
        for k in sorted(self.points.keys()):
            specs.append('/'.join([str(self.points[k]),str(k)]))
        return ','.join(specs)

    def to_spec_bool(self):
        if not self.points:
            return ''
        specs = []
        for k in sorted(self.points.keys()):
            specs.append('/'.join([self.bool2str(self.points[k]),str(k)]))
        return ','.join(specs)

    def __str__(self):
        return self.to_spec()

class Parser:

    class MatchedMessage(Enum):
        WastelandLocation = 0
        CampusReached = 1
        SupersteamUsed = 2
        RinoReached = 3
        Food = 4
        SpeedsUsed = 5
        Exhausted = 6
        PipBoy = 7
        Giant = 8
        GiantBattlefield = 9
        FailedToCraft = 10
        DeepRest = 11

    def __init__(self):

        self.status_line_regexp = re.compile('^(?:🚷 ?)?❤️(-?\d+)/(\d+) 🍗(\d+)% 🔋(\d+)/(\d+) 👣(\d+)км$',re.MULTILINE)
        self.food_regexp = re.compile('^🗃ПРИПАСЫ В РЮКЗАКЕ$',re.MULTILINE)
        self.food_line_regexp = re.compile('^▪️ +(.*?)/use_(\d+)$',re.MULTILINE)
        self.giant_hp_regexp = re.compile('^❤️(-?\d+)/(\d+)$',re.MULTILINE)

        #PipBoy lines
        self.pipboy_energy = re.compile('^🔋Выносливость: (\d+)/(\d+)$',re.MULTILINE)

        self.matched_message = None

        #stats
        self.hp = None
        self.max_hp = None
        self.hunger = None
        self.energy = None
        self.max_energy = None
        self.km = None

        #inventory related stuff
        self.food = []

    def parse_and_update(self, msg):

        self.matched_message = None
    
        print(msg)

        if msg.startswith('📟Пип-бой 3000'):
            #try to parse pip boy
            m = self.pipboy_energy.search(msg)
            if m:
                (self.energy, self.max_energy) = m.groups()
                self.matched_message = self.MatchedMessage.PipBoy

            m = self.food_regexp.search(msg)
            if m:
                self.food.clear()
                sub_state = 0 #initial state
                for s in msg.splitlines():
                    if sub_state==0:
                        if s=="Пища":
                            sub_state = 1
                            continue
                        self.food_parsed = True
                    elif sub_state==1:
                        if s=="Вещества":
                            break
                        m = self.food_line_regexp.match(s)
                        if not m:
                            print("failed to parse food line: %s" % s)
                            continue
                        (food_name, food_id) = m.groups()
                        self.food.append({ 'name': food_name, 'id': food_id })
                if self.food:
                    self.matched_message = self.MatchedMessage.Food
        elif msg=='Недостаточно ресурсов для изготовления предмета.':
            self.matched_message = self.MatchedMessage.FailedToCraft
        elif msg=='Ты добрался до своего лагеря.' or -1!=msg.find('Спустя какое-то время ты пришел в себя в своем лагере.') or -1!=msg.find('Здесь ты можешь отдохнуть от опасностей и сложностей Пустоши.'):
            self.matched_message = self.MatchedMessage.CampusReached
        elif msg.startswith('Ты слишком устал и не можешь идти дальше.') or msg.startswith('Ты слишком устал и не можешь отправиться в Пустошь.'):
            self.matched_message = self.MatchedMessage.Exhausted
        elif -1!=msg.find('Использован 💉++ Суперстим.'):
            self.matched_message = self.MatchedMessage.SupersteamUsed
        elif -1!=msg.find('Использован 💊Психостимулятор.'):
            self.matched_message = self.MatchedMessage.SpeedsUsed
        elif -1!=msg.find('Твой путь преградил исполинских размеров монстр.'):
            self.matched_message = self.MatchedMessage.Giant
        elif -1!=msg.find('Устроить привал /deeprest'):
            self.matched_message = self.MatchedMessage.DeepRest
        elif msg.startswith('Ты сейчас на поле боя с гигантом.') or msg.startswith('Твое местоположение: Возле гиганта'):
            m = self.giant_hp_regexp.search(msg)
            if m:
                self.matched_message = self.MatchedMessage.GiantBattlefield
                (self.giant_hp, self.giant_max_hp) = m.groups()
        elif msg.startswith('Некогда здесь был довольно большой, но в то же время уютный город Рино, а местные жители гордо называли его "Самый большой маленький городок в мире".'):
            self.matched_message = self.MatchedMessage.RinoReached
        else:
            m = self.status_line_regexp.search(msg)
            if m:
                (self.hp, self.max_hp, self.hunger, self.energy, self.max_energy, self.km) = m.groups()
                self.matched_message = self.MatchedMessage.WastelandLocation

    def __str__(self):
        def w(v):
            return v if v else 0
        return '❤️%s/%s 🍗%s%% 🔋%s/%s 👣%sкм' % (
            w(self.hp), w(self.max_hp),
            w(self.hunger),
            w(self.energy), w(self.max_energy),
            w(self.km)
        )

class Profile():

    def set_min_hp(self, spec):
        return self.min_hp.from_spec(spec)

    class ThresholdAction(Enum):
        gohome = 0
        stop = 1

    DUNGEONS_TO_SKIP_ON_SET_ALL = [19]

    def __init__(self):
        self.dungeons_autoenter = dict()

        self.darkzone_autoenter = {
            22: False,
            52: False,
            74: False
        }

    def load_from_file(self, fsm, filename):

        parser = configparser.ConfigParser()
        cfg = None

        if filename is None:
            parser['profile'] = {}
        else:
            parser.read(filename)

        cfg = parser['profile']

        self.min_hp = Intervals()
        if 'min_hp' in cfg:
            ret = self.min_hp.from_spec(cfg.get('min_hp'))
            if ret:
                raise Exception('failed to parse min_hp spec: ' + ret)

        self.cowardice = Intervals()
        if 'cowardice' in cfg:
            ret = self.cowardice.from_spec_bool(cfg.get('cowardice'))
            if ret:
                raise Exception('failed to parse cowardice spec: ' + ret)

        self.description = cfg.get('description') if 'description' in cfg else 'rename me'

        self.max_km_tresh = cfg.getint('max_km') if 'max_km' in cfg else 0
        self.min_hunger_tresh = cfg.getint('min_hunger') if 'min_hunger' in cfg else DEFAULT_HUNGER_TRHESHOLD
        self.autoloop = cfg.getboolean('autoloop') if 'autoloop' in cfg else False
        self.autojump12 = cfg.getboolean('autojump12') if 'autojump12' in cfg else False
        self.autojump22 = cfg.getboolean('autojump22') if 'autojump22' in cfg else False
        self.autojump31 = cfg.getboolean('autojump31') if 'autojump31' in cfg else False
        self.autospeeds = cfg.getboolean('autospeeds') if 'autospeeds' in cfg else False
        self.autoshoot = cfg.getboolean('autoshoot') if 'autoshoot' in cfg else False
        self.threshold_action = self.ThresholdAction[cfg.get('threshold_action')] if 'threshold_action' in cfg else self.ThresholdAction.gohome
        self.food_blacklist = cfg.get('food_blacklist').split(',') if 'food_blacklist' in cfg else []

        #ensure only one autojump is enabled
        if self.autojump12:
            self.autojump22 = False
            self.autojump31 = False
        elif self.autojump22:
            self.autojump31 = False

        dungeons_autoenter_list = cfg.get('autodunge') if 'autodunge' in cfg else None

        if dungeons_autoenter_list:
            if dungeons_autoenter_list=="all":
                for km,name in fsm.dungeons.items():
                    if km in self.DUNGEONS_TO_SKIP_ON_SET_ALL:
                        self.dungeons_autoenter[km] = False
                    else:
                        self.dungeons_autoenter[km] = True
            else:
                v = dungeons_autoenter_list.split(',')
                for km,name in fsm.dungeons.items():
                    if str(km) in v:
                        self.dungeons_autoenter[km] = True
                    else:
                        self.dungeons_autoenter[km] = False
        else:
            for km,name in fsm.dungeons.items():
                self.dungeons_autoenter[km] = False

        autodarkzone_list = cfg.get('autodarkzone') if 'autodarkzone' in cfg else None
        if autodarkzone_list:
            if autodarkzone_list=="all":
                for km in self.darkzone_autoenter.keys():
                    self.darkzone_autoenter[km] = True
            else:
                for km in autodarkzone_list.split(','):
                    km = int(km)
                    if km in self.darkzone_autoenter:
                        self.darkzone_autoenter[km] = True

    def save_to_file(self, filename):
        print('save to file:',filename)

        parser = configparser.ConfigParser()
        parser['profile'] = {}
        cfg = parser['profile']

        hp_spec = self.min_hp.to_spec()
        if hp_spec:
            cfg['min_hp'] = hp_spec

        cowardice_spec = self.cowardice.to_spec_bool()
        if cowardice_spec:
            cfg['cowardice'] = cowardice_spec

        cfg['description'] = self.description
        cfg['max_km'] = str(self.max_km_tresh)
        cfg['min_hunger'] = str(self.min_hunger_tresh)
        cfg['autoloop'] = str(self.autoloop)
        cfg['autojump12'] = str(self.autojump12)
        cfg['autojump22'] = str(self.autojump22)
        cfg['autojump31'] = str(self.autojump31)
        cfg['autospeeds'] = str(self.autospeeds)
        cfg['autoshoot'] = str(self.autoshoot)
        cfg['threshold_action'] = self.threshold_action.name

        if self.food_blacklist:
            cfg['food_blacklist'] = ','.join(self.food_blacklist)

        l = [str(km) for km,v in self.dungeons_autoenter.items() if v]
        if l:
            cfg['autodunge'] = ','.join(l)

        l = [str(km) for km,v in self.darkzone_autoenter.items() if v]
        if l:
            cfg['autodarkzone'] = ','.join(l)

        with open(filename, 'w') as f:
            parser.write(f)

    def get_food_blacklist(self):
        if not self.food_blacklist:
            return 'empty\n'
        s = ''
        for idx, prefix in enumerate(self.food_blacklist):
            s += '{}: {}\n'.format(idx,prefix)
        return s

    def is_food_blacklisted(self, food_name):
        for prefix in self.food_blacklist:
            if food_name.startswith(prefix):
                return True
        return False

    def __str__(self):
        return '''
description: %s
max km: %s
min hp: %s
min hunger: %s%%
cowardice: %s
action: %s
autoloop: %s
autoshoot: %s
autospeeds: %s
autojump12,22,31: %s %s %s
''' % (self.description,
       self.max_km_tresh, str(self.min_hp),
       self.min_hunger_tresh,
       self.cowardice.to_spec_bool(),
       self.threshold_action.name,
       self.autoloop,
       self.autoshoot,
       self.autospeeds,
       self.autojump12, self.autojump22, self.autojump31)

class FSM:

    class State(Enum):
        Journey = 0
        GoHome = 1
        Campus = 2
        Rino = 3
        Exhausted = 4
        Giant = 5

    def cancel_inactivity_timer(self):
        if self.inactivity_timer_task:
            self.inactivity_timer_task.cancel()
            self.inactivity_timer_task = None
            log('⏳inactivity timer is cancelled')

    def reset_inactivity_timer(self,event):
        self.cancel_inactivity_timer()

        def inactivity_timer_done_callback(f):
            try:
                r = f.result()
            except:
                pass

        log('⏳%s set inactivity timer' % event.message.id)

        self.inactivity_timer_task = asyncio.ensure_future(self.inactivity_timer_handler(event))
        self.inactivity_timer_task.add_done_callback(inactivity_timer_done_callback)

    async def inactivity_timer_handler(self,event):
        try:
            delay = random.randint(int(INACTIVITY_POLL_TIMEOUT*0.9),int(INACTIVITY_POLL_TIMEOUT*1.1))
            log('⏳%s inactivity timer delay: %s' % (event.message.id,delay))
            if os.name == 'nt': #TODO: check what is wrong with asyncio.sleep on windows
                time.sleep(delay)
            else:
                await asyncio.sleep(delay)
            await self.on_inactivity_timer(event)
        except:
            return

    async def on_inactivity_timer(self,event):
        log('⏳inactivity timer is fired')
        if not self.enabled:
            log('⏳ignore timer because of disabled events processing')
            return
        if self.skip_buttons:
            log('⏳ignore timer because of disabled buttons processing')
            return
        await self.delayed_reply(event,'🔎Действие')

    def on_go_further(self, event, button):
        if self.state!=self.State.Journey:
            return None
        return button

    def on_dunge_go_further(self, event, button):
        return button

    def on_fight(self, event, button):
        return button

    def on_cowardice(self, event, button):
        if self.parser.matched_message!=Parser.MatchedMessage.WastelandLocation:
            return None
        if self.parser.km:
            if self.p().cowardice.get(int(self.parser.km)):
                return button
        return None

    def on_shoot(self, event, button):
        if self.p().autoshoot:
            return button
        return None

    def on_go_home(self, event, button):
        #press button only if we are in GoHome state
        if self.state != self.State.GoHome:
            return None
        return button

    def on_go_home_confirm(self, event, button):
        #press button only if we are in GoHome state
        if self.state != self.State.GoHome:
            return None
        #self.state = self.State.Journey
        return button

    def on_jump12(self, event, button):
        if self.p().autojump12:
            return button
        return None

    def on_jump22(self, event, button):
        if self.p().autojump22:
            return button
        return None

    def on_jump31(self, event, button):
        if self.p().autojump31:
            return button
        return None

    def on_darkzone(self, event, button):
        if self.parser.matched_message!=Parser.MatchedMessage.WastelandLocation:
            return None
        if self.parser.km:
            km = int(self.parser.km)
            if km in self.p().darkzone_autoenter and self.p().darkzone_autoenter[km]:
                return button
        return None

    def on_dunge_enter(self, event, button):
        if self.parser.matched_message!=Parser.MatchedMessage.WastelandLocation:
            return None
        if self.parser.km:
            km = int(self.parser.km)
            if km in self.p().dungeons_autoenter and self.p().dungeons_autoenter[km]:
                return button
        return None

    class Button:
        def __init__(self, name, handler):
            self.name = name
            self.handler = handler

        def match(self, key):
            return self.name==key

        def process(self, fsm, event, button):
            return self.handler(fsm, event, button)

    buttons = [
        Button('⛺️Вернуться',on_go_home),
        Button('Вернуться в лагерь',on_go_home_confirm),
        Button('🔜12 км',on_jump12),
        Button('🔜22 км',on_jump22),
        Button('🔜31 км',on_jump31),
        Button('🚷В Темную зону',on_darkzone),
        Button('🔫Выстрелить',on_shoot),
        Button('👣Идти дальше',on_go_further),
        Button('👣Идти дaльше',on_go_further), #changed 'a' to ascii
        Button('Двигаться дальше',on_dunge_go_further),
        Button('Идти вглубь',on_dunge_go_further),
        Button('🏃Дать деру',on_cowardice),
        Button('⚔️Дать отпор',on_fight)
    ]
    DUNGEONS_BUTTON_INSERT_IDX = 2

    dungeons = {
        11: "Старая шахта",
        19: "⚠️Пещера Ореола",
        23: "🚽Сточная труба",
        29: "⚙️Открытое убежище",
        34: "🦇Бэт-пещера",
        39: "🦆Перевал Уткина",
        45: "🌁Высокий Хротгар",
        51: "🛏Безопасный привал",
        50: "🛑Руины Гексагона",
        56: "🔬Научный комплекс",
        69: "⛩Храм Испытаний",
        74: "🗨Черная Меза",
        80: "🔥Огненные недра"
    }

    profiles = dict()

    def p(self, idx = None):
        if idx is None:
            idx = self.active_profile
        return self.profiles[idx]

    def load_profiles(self):
        if os.path.isdir(PROFILES_DIR):
            flist = [f for f in os.listdir(PROFILES_DIR)]
            if flist:
                print('load {} profiles'.format(len(flist)))
                for f in flist:
                    profile_idx = int(f)
                    profile_path = PROFILES_DIR + '/' + f
                    if not os.path.isfile(profile_path):
                        continue
                    self.profiles[profile_idx] = Profile()
                    self.profiles[profile_idx].load_from_file(self,profile_path)
                self.active_profile = sorted(self.profiles.keys())[0]
                return
        else:
            os.mkdir(PROFILES_DIR)

        if self.profiles:
            return

        # no profiles. create default one with idx 0

        self.profiles[0] = Profile()
        self.active_profile = 0
        self.p().load_from_file(self, None)
        self.p().save_to_file(PROFILES_DIR + '/' + str(self.active_profile))

    def save_profiles(self):
        for idx,p in self.profiles.items():
            p.save_to_file(PROFILES_DIR + '/' + str(idx))

    def __init__(self):

        self.runtime_version = self.on_version(None,None,True)

        self.enabled = True
        self.parser = Parser()
        self.state = self.State.Journey
        self.skip_buttons = False
        self.inactivity_timer_task = None

        self.food_requested = False

        #init dounges buttons callbacks
        for name in self.dungeons.values():
            self.buttons.insert(self.DUNGEONS_BUTTON_INSERT_IDX, self.Button(name,FSM.on_dunge_enter))

        self.load_profiles()

    async def delayed_reply(self, event, reply, delay = None, skip_inactivity_timer = False):
        if not delay:
            delay = random.randint(MIN_RESPONSE_DELAY,MAX_RESPONSE_DELAY)
        elif isinstance(delay,tuple):
            delay = random.randint(delay[0],delay[1])
        else:
            delay = random.randint(delay*0.8,delay*1.2)

        log('⏳%s postpone %s for %s seconds' % (event.message.id,reply,delay))

        if os.name == 'nt': #TODO: check what is wrong with asyncio.sleep on windows
            time.sleep(delay)
        else:
            await asyncio.sleep(delay)

        await event.respond(reply)
        log('👌%s sent: %s' % (event.message.id,reply))

        if not skip_inactivity_timer:
            self.reset_inactivity_timer(event)

    def on_threshold_matched(self):
        if self.p().threshold_action==Profile.ThresholdAction.gohome:
            log('threshold action is gohome. change fsm state to GoHome')
            self.state = self.State.GoHome
        elif self.p().threshold_action==Profile.ThresholdAction.stop:
            log('threshold action is stop. disable events processing')
            self.enabled = False
        else:
            log('ERROR: unexpected threshold action %s. disable events processing' % self.p().threshold_action)
            self.enabled = False

    async def handle_state(self,event):

        #process matched messages

        if self.parser.matched_message:
            #cancel inactivity timer on any known input
            self.cancel_inactivity_timer()

        if self.parser.matched_message==Parser.MatchedMessage.CampusReached:
            self.state = self.State.Campus
            self.sub_state = 0
        elif self.parser.matched_message==Parser.MatchedMessage.RinoReached:
            self.state = self.State.Rino
            self.sub_state = 0
        elif self.parser.matched_message==Parser.MatchedMessage.WastelandLocation:
            self.state = self.State.Journey
            log('%s %s' % (event.message.id,str(self.parser)))
            if self.parser.hunger and self.p().min_hunger_tresh and int(self.parser.hunger) > self.p().min_hunger_tresh:
                log('%s I am hungry. ask for food' % event.message.id)
                self.food_requested = True
                await self.delayed_reply(event,'/myfood')
        elif self.parser.matched_message==Parser.MatchedMessage.Food:
            if self.food_requested:
                self.food_requested = False
                found = False
                for f in self.parser.food:
                    if self.p().is_food_blacklisted(f['name']):
                        log('%s got menu. skip blacklisted %s' % (event.message.id,f['name']))
                        continue
                    log('%s got menu. eat the first one not blacklisted from the list: %s' % (event.message.id,f['name']))
                    await self.delayed_reply(event,'/use_%s' % f['id'])
                    found = True
                    break
                if not found:
                    await client.send_message(ctl_chat_id, 'attention required\nno more allowed food')
            else:
                log('%s got menu. ignore because requested by player manually' % (event.message.id))
        elif self.parser.matched_message==Parser.MatchedMessage.Exhausted:
            log('%s got exhaustion message' % (event.message.id))
            if self.state != self.State.Exhausted:
                self.prev_state = self.state
            self.state = self.State.Exhausted
            self.skip_buttons = True
            await self.delayed_reply(event,'/me',EXHAUSTED_MODE_DELAY, True)
        elif self.parser.matched_message==Parser.MatchedMessage.Giant:
            if self.state != self.State.Giant:
                self.prev_state = self.state
            self.state = self.State.Giant
            self.skip_buttons = True
            await self.delayed_reply(event,'🔎Действие',GIANT_POLL_INTERVAL, True)
        elif self.parser.matched_message==Parser.MatchedMessage.DeepRest:
            await self.delayed_reply(event,'/deeprest')

        #process states

        if self.state==self.State.Journey:
            if self.parser.matched_message==Parser.MatchedMessage.GiantBattlefield:
                if int(self.parser.giant_hp) < 0:
                    await self.delayed_reply(event,'⚔️Атаковать')
                else:
                    #enter giant poll cycle
                    if self.state != self.State.Giant:
                        self.prev_state = self.state
                    self.state = self.State.Giant
                    self.skip_buttons = True
                    await self.delayed_reply(event,'🔎Действие',GIANT_POLL_INTERVAL)
            if self.parser.matched_message==Parser.MatchedMessage.WastelandLocation:
                if self.parser.hp and self.parser.km and int(self.parser.hp) <= self.p().min_hp.get(int(self.parser.km)):
                    log('%s min hp treshold reached' % event.message.id)
                    self.on_threshold_matched()
                    return
                if self.parser.km and self.p().max_km_tresh and int(self.parser.km) >= self.p().max_km_tresh:
                    log('%s max km treshold reached' % event.message.id)
                    self.on_threshold_matched()
                    return
        elif self.state==self.State.Exhausted:
            if self.parser.matched_message==Parser.MatchedMessage.PipBoy:
                if int(self.parser.energy) > 0:
                    #restore previous state. enable buttons processing and request for available actions
                    self.state = self.prev_state
                    self.skip_buttons = False
                    if self.state==self.State.Campus:
                        await self.delayed_reply(event,'👣Пустошь')
                    else:
                        await self.delayed_reply(event,'🔎Действие')
                else:
                    #continue energy waiting cycle
                    await self.delayed_reply(event,'/me',EXHAUSTED_MODE_DELAY)
        elif self.state==self.State.Giant:
            if self.parser.matched_message==Parser.MatchedMessage.GiantBattlefield:
                if int(self.parser.giant_hp) < 0:
                    #restore previous state. enable buttons processing and press '⚔️Атаковать' button
                    self.state = self.prev_state
                    self.skip_buttons = False
                    await self.delayed_reply(event,'⚔️Атаковать')
                else:
                    #continue giant poll cycle
                    await self.delayed_reply(event,'🔎Действие',GIANT_POLL_INTERVAL)
            else:
                # ~ log('%s unexpected giant disappearance. change state to the previous one. report to ctl chat' % event.message.id)
                self.skip_buttons = False
                self.state = self.prev_state
                # ~ await client.send_message(ctl_chat_id, 'attention required\nunexpected giant disappearance')
        elif self.state==self.State.GoHome:
            if (self.parser.hp and int(self.parser.hp) > self.p().min_hp.get(int(self.parser.km)) and
                self.parser.km and self.p().max_km_tresh and int(self.parser.km) < self.p().max_km_tresh):
                log('%s we have more than min hp and less than max km in GoHome state. change state to Journey' % event.message.id)
                self.state = self.State.Journey
        elif self.state==self.State.Campus:
            if self.sub_state==0:
                log('{} campus. hp state: {}/{}'.format(event.message.id,self.parser.hp,self.parser.max_hp))
                if self.parser.hp and self.parser.max_hp and int(self.parser.hp) <  int(self.parser.max_hp):
                    self.sub_state = 1
                    await self.delayed_reply(event,'💉++ Суперстим')
                else:
                    if self.p().autospeeds:
                        self.sub_state = 2
                        await self.delayed_reply(event,'💊Speed-ы')
                    else:
                        self.sub_state = 3
                        if self.p().autoloop:
                            await self.delayed_reply(event,'👣Пустошь')
            elif self.sub_state==1 and (self.parser.matched_message==Parser.MatchedMessage.SupersteamUsed or self.parser.matched_message==Parser.MatchedMessage.FailedToCraft):
                if self.p().autospeeds:
                    self.sub_state = 2
                    await self.delayed_reply(event,'💊Speed-ы')
                else:
                    self.sub_state = 3
                    if self.p().autoloop:
                        await self.delayed_reply(event,'👣Пустошь')
            elif self.sub_state==2 and (self.parser.matched_message==Parser.MatchedMessage.SpeedsUsed or self.parser.matched_message==Parser.MatchedMessage.FailedToCraft):
                self.sub_state = 3
                if self.p().autoloop:
                    await self.delayed_reply(event,'👣Пустошь')
        elif self.state==self.State.Rino:
            if self.sub_state==0:
                pass
                #  1. refill 💌 Медпак, 💉 Мед-Х, 💊 Баффаут (parse /mystock and buy related items)
            elif self.sub_state==1:
                pass
                #  2. sell materials (Обменять все)
            elif self.sub_state==2:
                pass
                #  3. increase stats (parse 🎓Обучение output)
            elif self.sub_state==3:
                pass
                #  4. go to wasteland (👣Пустошь)

    def process_buttons(self, event):
        if self.skip_buttons:
            log('%s buttons processing is disabled' % event.message.id)
            return

        if not event.message.reply_markup:
            # ~ log('%s no buttons in reply' % event.message.id)
            return None

        for row in event.message.reply_markup.rows:
            for button in row.buttons:
                log("%s '%s'" % (event.message.id,button.text))

        for b in self.buttons:
            for row in event.message.reply_markup.rows:
                for button in row.buttons:
                    # ~ log('%s process button: %s' % (event.message.id,button.text))
                    if b.match(button.text):
                        log('%s matched button: %s' % (event.message.id,button.text))
                        reply = b.process(self, event, button.text)
                        if(reply):
                            return reply

    async def handle_incoming_message(self, event):

        self.parser.parse_and_update(event.raw_text)

        if not self.enabled:
            return None

        await self.handle_state(event)

        if not self.enabled:
            return None

        return self.process_buttons(event)

    def on_help(self, event, text):
        return '''
s - show status
e - switch events processing (%s)
r - reset. set processing ctl flags and FSM state to the initial values
? - this help
v - show version
update - load bot updates
restart - restart bot instance
quit - shutdown bot instance

thresholds:
hpX - set minimal hp threshold to X for all kilometers
hpX/Y - set minimal hp threshold to X for Y kilometer and beyond
hX - set minimal hunger threshold to X (%s)
kmX - set maximum km threshold to X (%s)
a - action / change threshold action (%s)

cX/Y[,X2,Y2...] - set cowardice intervals.
like for hp, but possible values for X are:
  * true,1,t,y,yes,yeah,yup - to specify True
  * false,0,f,n,no,nope - to specify False

switchers:
l - loop / autoloop (%s)
m - maniac / autoshoot (%s)
speed - speeds usage in campus (%s)
j[12,22,31] - switch autojump[12,22,31] (%s,%s,%s)

darkzone control:
z - list darkzone autoenter kilometers
za - enable darkzone autoenter for all known kilometers
zd - disable darkzone autoenter for all known kilometers
zX - switch darkzone autoenter for X kilometer

dungeons control:
d - list known dungeons with actual autoenter settings
da - enable autoenter for all dungeons except of the one on 19km
dd - disable autoenter for all dungeons
da>X/da<X - enable autoenter for all dungeons after/before X km
dd>X/dd<X - disable autoenter for all dungeons after/before X km
dX - switch autoenter for dungeon on X kilometer

profiles control:
p - profiles short list (active, idx, description)
pl - profiles detailed list
pX - switch to the profile with index X
psX - show details of the profile with index X
pcX - copy active profile to the profile with index X
pdX DESC - set description DESC for the profile with index X
prX - remove profile with index X (must be inactive)

food control:
f - show food blacklist
fa PREFIX - append food blacklist with PREFIX
frX - remove food blacklist item by index X
fsX PREFIX - set food blacklist item by index X to the prefix PREFIX
fc - clear food blacklist
''' % (self.enabled,
       self.p().min_hunger_tresh,
       self.p().max_km_tresh,
       self.p().threshold_action.name,
       self.p().autoloop,
       self.p().autoshoot,
       self.p().autospeeds,
       self.p().autojump12, self.p().autojump22, self.p().autojump31)

    def on_status(self, event, text):
        return '''
events_processing: %s
buttons_processing: %s
fsm_state: %s
%s

max km: %s
min hp: %s
min hunger: %s%%
cowardice: %s
action: %s

autoloop: %s
autoshoot: %s
autospeeds: %s
autojump12,22,31: %s %s %s
''' % (self.enabled,
       not self.skip_buttons,
       self.state.name,
       str(self.parser),
       self.p().max_km_tresh, str(self.p().min_hp),
       self.p().min_hunger_tresh,
       self.p().cowardice.to_spec_bool(),
       self.p().threshold_action.name,
       self.p().autoloop,
       self.p().autoshoot,
       self.p().autospeeds,
       self.p().autojump12, self.p().autojump22, self.p().autojump31)

    def on_events_processing(self, event, text):
        self.enabled = not self.enabled
        if self.enabled:
            return 'events processing is enabled'
        else:
            return 'events processing is disabled'

    def on_quit(self, event, text):
        os.kill(os.getpid(), signal.SIGTERM)

    def on_set_min_hp(self, event, text):
        ret = self.p().min_hp.from_spec(text[2:])
        if ret:
            return ret
        return 'minimal hp threshold changed to:\n%s' % str(self.p().min_hp)

    def on_set_cowardice(self, event, text):
        ret = self.p().cowardice.from_spec_bool(text[1:])
        if ret:
            return ret
        return 'cowardice updated:\n%s' % self.p().cowardice.to_spec_bool()

    def on_set_min_hunger(self, event, text):
        try:
            self.p().min_hunger_tresh = int(text[1:])
            return 'min hunger tresh is set to: %s%%' % self.p().min_hunger_tresh
        except:
            return 'failed to parse input'

    def on_set_max_km(self, event, text):
        try:
            self.p().max_km_tresh = int(text[2:])
            return 'maximum km threshold is set to: %s' % self.p().max_km_tresh
        except:
            return 'failed to parse input'

    def on_autoloop(self, event, text):
        self.p().autoloop = not self.p().autoloop
        if self.p().autoloop:
            return 'autoloop enabled'
        else:
            return 'autoloop disabled'

    def on_autojump12(self, event, text):
        self.p().autojump12 = not self.p().autojump12
        if self.p().autojump12:
            self.p().autojump22 = False
            self.p().autojump31 = False
            return 'autojump12 enabled. other jumps disabled'
        else:
            return 'autojump12 disabled'

    def on_autojump22(self, event, text):
        self.p().autojump22 = not self.p().autojump22
        if self.p().autojump22:
            self.p().autojump12 = False
            self.p().autojump31 = False
            return 'autojump22 enabled. other jumps disabled'
        else:
            return 'autojump22 disabled'

    def on_autojump31(self, event, text):
        self.p().autojump31 = not self.p().autojump31
        if self.p().autojump31:
            self.p().autojump12 = False
            self.p().autojump22 = False
            return 'autojump31 enabled. other jumps disabled'
        else:
            return 'autojump31 disabled'

    def on_faster(self, event, text):
        self.p().autospeeds = not self.p().autospeeds
        if self.p().autospeeds:
            return 'autospeeds enabled'
        else:
            return 'autospeeds disabled'

    def on_autoshoot(self, event, text):
        self.p().autoshoot = not self.p().autoshoot
        if self.p().autoshoot:
            return 'autoshoot enabled'
        else:
            return 'autoshoot disabled'

    def on_autodarkzone(self, event, text):
        cmd = text[1:]
        if not cmd:
            return self.get_darkzone_autoenter_status()

        if cmd=='a':
            for km in self.p().darkzone_autoenter.keys():
                self.p().darkzone_autoenter[km] = True
            return self.get_darkzone_autoenter_status()

        if cmd=='d':
            for km in self.p().darkzone_autoenter.keys():
                self.p().darkzone_autoenter[km] = False
            return self.get_darkzone_autoenter_status()

        try:
            km = int(cmd)
            if km not in self.p().darkzone_autoenter:
                return "have no info about darkzone on {} km. nothing changed".format(km)
            self.p().darkzone_autoenter[km] = not self.p().darkzone_autoenter[km]
            return self.get_darkzone_autoenter_status(km)
        except:
            pass

        return 'unknown darkzone control command. check help for available commands'


    def on_profiles(self, event, text):
        cmd = text[1:]
        if not cmd:
            s = ''
            for idx in sorted(self.profiles.keys()):
                if idx==self.active_profile:
                    s+='*'
                s+=str(idx) + ': ' + self.profiles[idx].description + '\n'
            return s

        try:
            if cmd[0]=='s':
                cmd = cmd[1:]
                idx = int(cmd)
                if idx not in self.profiles:
                    return 'no profile with index: ' + cmd
                s=str(self.profiles[idx])
                s+='\ndarkzone autoenter:\n'
                s+=self.get_darkzone_autoenter_status(None,idx)
                s+='\ndungeons autoenter:\n'
                s+=self.get_dungeons_autoenter_status(None,idx)
                s+='\nfood blacklist:\n'
                s+=self.profiles[idx].get_food_blacklist()
                return s
            elif cmd[0]=='l':
                s = ''
                for idx in sorted(self.profiles.keys()):
                    s += '-----BEGIN PROFILE {}-----\n'.format(idx)
                    s+='active: {}\n'.format(idx==self.active_profile)
                    s+=str(self.profiles[idx])
                    s+='\ndarkzone autoenter:\n'
                    s+=self.get_darkzone_autoenter_status(None,idx)
                    s+='\ndungeons autoenter:\n'
                    s+=self.get_dungeons_autoenter_status(None,idx)
                    s+='\nfood blacklist:\n'
                    s+=self.profiles[idx].get_food_blacklist()
                    s+= '-----END PROFILE {}-----\n\n'.format(idx)
                return s
            elif cmd[0]=='c':
                cmd = cmd[1:]
                idx = int(cmd)
                if idx==self.active_profile:
                    return 'attempt to overwrite active profile. ignored'
                self.profiles[idx] = copy.deepcopy(self.profiles[self.active_profile])
                return 'active profile was copied {} -> {}'.format(self.active_profile,idx)
            elif cmd[0]=='d':
                cmd = cmd[1:]
                v = cmd.split(' ')
                if len(v)!=2:
                    return 'wrong profile description change command syntax'
                idx = int(v[0])
                if idx not in self.profiles:
                    return 'no profile with index: ' + cmd
                self.profiles[idx].description = v[1]
                return 'description for profile {} changed to: {}'.format(idx,v[1])
            elif cmd[0]=='r':
                cmd = cmd[1:]
                idx = int(cmd)
                if idx==self.active_profile:
                    return 'attempt to remove active profile. ignored'
                if idx not in self.profiles:
                    return 'no profile with index: ' + cmd
                del self.profiles[idx]
                try:
                    os.remove('{}/{}'.format(PROFILES_DIR,idx))
                except:
                    pass
                return 'removed profile with idx' + cmd
            else:
                idx = int(cmd)
                if idx not in self.profiles:
                    return 'no profile with index: ' + cmd
                self.active_profile = idx
                return 'switched to the profile: ' + str(self.active_profile)
        except:
            pass

        return 'invalid profiles control command'

    def on_food(self, event, text):
        cmd = text[1:]
        if not cmd:
            return 'food blacklist:\n' + self.p().get_food_blacklist()
        try:
            if cmd.startswith('a '):
                prefix = cmd[2:]
                if not prefix:
                    return 'wrong food apppend command syntax'
                self.p().food_blacklist.append(prefix)
                return 'food blacklist appended with prefix: ' + prefix
            elif cmd[0]=='r':
                idx = int(cmd[1:])
                if idx < 0 or idx >= len(self.p().food_blacklist):
                    return 'invalid idx: ' + str(idx)
                del self.p().food_blacklist[idx]
                return 'removed food blacklist entry by index {}'.format(idx)
            elif cmd[0]=='s':
                cmd = cmd[1:]
                v = cmd.split(' ',1)
                print(v)
                if len(v)!=2:
                    return 'wrong food set command syntax'
                idx = int(v[0])
                prefix = v[1]
                if idx < 0 or idx >= len(self.p().food_blacklist):
                    return 'invalid idx: ' + str(idx)
                self.p().food_blacklist[idx] = prefix
                return 'food blacklist entry by index {} is set to: {}'.format(idx,prefix)
            elif cmd[0]=='c':
                self.p().food_blacklist = []
                return 'food blacklist cleared'
        except:
            pass

        return 'invalid food control command'

    def on_threshold_action(self, event, text):
        self.p().threshold_action = Profile.ThresholdAction((self.p().threshold_action.value + 1 ) % 2)
        return 'threshold action changed to: %s' % self.p().threshold_action.name

    def get_dungeons_autoenter_status(self, km = None, idx = None):
        if km:
            return "{} {} {}\n".format(
                    '✔' if self.p(idx).dungeons_autoenter[km] else '❌',
                    km, self.dungeons[km])
        else:
            s = ''
            for km in sorted(self.dungeons.keys()):
                s += "{} {} {}\n".format(
                    '✔' if self.p(idx).dungeons_autoenter[km] else '❌',
                    km, self.dungeons[km])
            return s

    def get_darkzone_autoenter_status(self, km = None, idx = None):
        if km:
            return "{} {}\n".format('✔' if self.p(idx).darkzone_autoenter[km] else '❌', km)
        else:
            s = ''
            for km in sorted(self.p(idx).darkzone_autoenter.keys()):
                s += "{} {}\n".format(
                    '✔' if self.p(idx).darkzone_autoenter[km] else '❌', km)
            return s

    def on_dunge_ctl(self, event, text):
        cmd = text[1:]

        if not cmd:
            return self.get_dungeons_autoenter_status()

        range_modify_to = None

        if cmd.startswith('a'):
            cmd = cmd[1:]
            if not cmd:
                for km in self.p().dungeons_autoenter.keys():
                    if km not in self.DUNGEONS_TO_SKIP_ON_SET_ALL:
                        self.p().dungeons_autoenter[km] = True
                return self.get_dungeons_autoenter_status()
            else:
                 range_modify_to = True
        elif cmd.startswith('d'):
            cmd = cmd[1:]
            if not cmd:
                for km in self.p().dungeons_autoenter.keys():
                    self.p().dungeons_autoenter[km] = False
                return self.get_dungeons_autoenter_status()
            else:
                range_modify_to = False

        if range_modify_to is not None:
            vmin = 0
            vmax = 0
            try:
                if cmd.startswith('>'):
                    vmin = int(cmd[1:])
                elif cmd.startswith('<'):
                    vmax = int(cmd[1:])
                else:
                    return 'invalid range specification. check help'

                for km in self.dungeons_autoenter.keys():
                    if (km > vmin) and (vmax==0 or km < vmax):
                        self.p().dungeons_autoenter[km] = range_modify_to

                return self.get_dungeons_autoenter_status()

            except:
                 pass

            return 'failed to parse dungeon control command for range. check help'

        try:
            km = int(cmd)
            if km not in self.dungeons:
                return "have no info about dungeon on {} km. nothing changed".format(km)
            self.p().dungeons_autoenter[km] = not self.p().dungeons_autoenter[km]
            return self.get_dungeons_autoenter_status(km)
        except:
            pass

        return 'unknown dungeon control command. check help for available commands'

    def on_ctl_reset(self, event, text):
        self.enabled = True
        self.skip_buttons = False
        self.state = self.State.Journey
        self.food_requested = False
        return 'processing control flags and FSM state are set to the initial values'

    def on_version(self,event, text, startup = False):
        msg = ""

        if not startup:
            msg += "runtime:  \n" + self.runtime_version + "\n"
            msg += "fs:\n"

        msg += "  tags: "
        msg+= subprocess.Popen("git describe --tags", shell=True, stdout=subprocess.PIPE).communicate()[0].decode("utf-8")
        msg += "  commit: "
        msg+= subprocess.Popen("git rev-parse HEAD", shell=True, stdout=subprocess.PIPE).communicate()[0].decode("utf-8")

        return msg

    def on_update(self,event, text):
        msg = ''
        out,err = subprocess.Popen("git pull", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
        if out:
            msg+=out.decode("utf-8")
        if err:
            msg+=err.decode("utf-8")
        return msg

    def on_restart(self,event, text):
        if SIGHUP_AVAILABLE:
            os.kill(os.getpid(), signal.SIGHUP)
        else:
            return "self restart has not available on this platform yet"

    class CtrlCmd:
        def __init__(self, key, handler, exact_match = True):
            self.key = key
            self.handler = handler
            self.exact_match = exact_match

        def match(self, msg):
            if self.exact_match:
                return msg==self.key
            return msg.startswith(self.key)

        def process(self, fsm, event, msg):
            return self.handler(fsm, event, msg)

    control_commands = [
        CtrlCmd('s',on_status),
        CtrlCmd('e',on_events_processing),
        CtrlCmd('a',on_threshold_action),
        CtrlCmd('z',on_autodarkzone, False),
        CtrlCmd('p',on_profiles, False),
        CtrlCmd('f',on_food,False),
        CtrlCmd('?',on_help),
        CtrlCmd('quit',on_quit),
        CtrlCmd('update',on_update),
        CtrlCmd('restart',on_restart),
        CtrlCmd('speed',on_faster),
        CtrlCmd('l',on_autoloop),
        CtrlCmd('m',on_autoshoot),
        CtrlCmd('r',on_ctl_reset),
        CtrlCmd('v',on_version),
        CtrlCmd('j12',on_autojump12),
        CtrlCmd('j22',on_autojump22),
        CtrlCmd('j31',on_autojump31),
        CtrlCmd('hp',on_set_min_hp, False),
        CtrlCmd('c',on_set_cowardice, False),
        CtrlCmd('h',on_set_min_hunger, False),
        CtrlCmd('km',on_set_max_km, False),
        CtrlCmd('d',on_dunge_ctl, False)
    ]

    def handle_incoming_control_message(self, event):
        for cmd in self.control_commands:
            if cmd.match(event.raw_text):
                reply = cmd.process(self, event, event.raw_text)
                if reply:
                    return reply
                return
        return self.on_help(event, event.raw_text)

    async def handle_incoming_broadcast_message(self, event):
        if self.stealth:
            #~ log('💤%s broadcast event ignored because stealth mode is enabled' % event.message.id)
            return
        if '/get_chat_id'==event.raw_text:
            await event.respond(event.message.to_id.stringify())

cfg = configparser.ConfigParser()
cfg.read('wwalker.cfg')

for s in ['api','bot']:
    if not s in cfg:
        raise Exception('missed mandatory section [%s]' % s)
for opt in ['id','hash']:
    if opt not in cfg['api']:
        raise Exception('missed mandatory option "%s" in section [api]' % opt)
for opt in ['ctl_chat_id']:
    if opt not in cfg['bot']:
        raise Exception('missed mandatory option "%s" in section [bot]' % opt)

fsm = FSM()

client = TelegramClient('wwalker', cfg['api'].getint('id'), cfg['api']['hash'])

ctl_chat_id = cfg['bot'].getint('ctl_chat_id')

disconnect_task = None
restart = False

def sighup_handler(signum, frame):
    global restart
    restart = True
    log('got SIGHUP. restart instance')
    asyncio.ensure_future(client.disconnect())

def terminate_handler(signum, frame):
    log('terminate instance')
    asyncio.ensure_future(client.disconnect())

if SIGHUP_AVAILABLE:
    signal.signal(signal.SIGHUP, sighup_handler)

signal.signal(signal.SIGINT, terminate_handler)
signal.signal(signal.SIGTERM, terminate_handler)

@client.on(events.NewMessage(incoming=True, chats=['WastelandWarsBot']))
async def handler(event):
    log('👀%s got update from WW' % event.message.id)

    try:
        reply = await fsm.handle_incoming_message(event)
    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        log('🖕%s exception %s\n%s %s:%s' % (event.message.id,e,exc_type,fname,exc_tb.tb_lineno))
        await client.send_message(ctl_chat_id, '🖕%s exception %s\n%s %s:%s' % (event.message.id,e,exc_type,fname,exc_tb.tb_lineno))

    if reply:
        await fsm.delayed_reply(event,reply)
    # ~ else:
        # ~ log('💤%s no reply generated by fsm' % event.message.id)

@client.on(events.NewMessage(outgoing=True, chats=[ctl_chat_id]))
async def ctl_handler(event):
    log('👀%s got ctl request: %s' % (event.message.id, event.raw_text))
    try:
        reply = fsm.handle_incoming_control_message(event)
    except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        log('🖕%s exception %s\n%s %s:%s' % (event.message.id,e,exc_type,fname,exc_tb.tb_lineno))
        await client.send_message(ctl_chat_id, '🖕%s exception %s\n%s %s:%s' % (event.message.id,e,exc_type,fname,exc_tb.tb_lineno))

    if(reply):
        await event.respond(reply)

@client.on(events.NewMessage())
async def any_handler(event):
    #~ log('👀%s got broadcast request' % event.message.id)
    await fsm.handle_incoming_broadcast_message(event)

hi_msg = 'started new instance %s with version:\n%s' % (os.getpid(),fsm.runtime_version)
log(hi_msg)

client.start()
# ~ client.send_message(ctl_chat_id, hi_msg)
client.run_until_disconnected()

fsm.save_profiles()

if restart:
    log('replace instance %s' % os.getpid())
    os.execl('/usr/bin/python3','-c',__file__)
else:
    log('bye')

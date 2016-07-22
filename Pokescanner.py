# encoding: utf-8

import threading
import time
import requests
import json
import re
import pokemon_pb2
import struct

from geopy import GoogleV3
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from requests.adapters import ConnectionError
from requests.models import InvalidURL
from s2sphere import *
from google.protobuf.internal import encoder
from datetime import datetime

API_URL = 'https://pgorelease.nianticlabs.com/plfe/rpc'
LOGIN_URL = 'https://sso.pokemon.com/sso/login?service=https%3A%2F%2Fsso.pokemon.com%2Fsso%2Foauth2.0%2FcallbackAuthorize'
LOGIN_OAUTH = 'https://sso.pokemon.com/sso/oauth2.0/accessToken'
PTC_CLIENT_SECRET = 'w8ScCUXJQc6kXKw8FiOhd8Fixzht18Dq3PEVkUCP5ZPxtgyWsbTvWHFLm2wNY0JR'


def f2i(float_val):
    return struct.unpack('<Q', struct.pack('<d', float_val))[0]


def encode(cellid):
    output = []
    encoder._VarintEncoder()(output.append, cellid)
    return ''.join(output)


def ms_dif_to_now(start_time):
    dt = datetime.now() - start_time
    ms = (dt.days * 24 * 60 * 60 + dt.seconds) * 1000 + dt.microseconds / 1000.0
    return ms


class Pokescanner (threading.Thread):
    def __init__(self, threadID, name, username, password, location, step_limit, pokemonJSON):
        threading.Thread.__init__(self)
        requests.packages.urllib3.disable_warnings()
        self.threadID = threadID
        self.name = name
        self.username = str(username)
        self.password = str(password)
        self.location_str = location
        self.step_limit = step_limit
        self.pokemonJSON = pokemonJSON
        self.wild_pokemon_list = []
        self.last_scan_num_found = 0
        self.last_scan_completed = None
        self.do_scan = True
        self.start_scan = True
        self.restart_count = 0
        self.latitude = 0
        self.orglatitude = 0
        self.longitude = 0
        self.orglongitude = 0
        self.altitude = 0
        self.access_token = None
        self.api_endpoint = ''
        self.profile_response = None
        self.session = requests.session()
        self.session.headers.update({'User-Agent': 'Niantic App'})
        self.session.verify = False
        self.debuglvl = 0
        self.scan_count = 0
        self.need_restart = False

    def log(self, msg, lvl=0):
        # 0 info
        # 1 error
        if lvl < self.debuglvl:
            return
        prefix = '[.]'
        if lvl == 1:
            prefix = '[-]'
            return
        if lvl > 1:
            prefix = '[!]'
        print 'ID{}({}):{} {}'.format(self.threadID, time.strftime("%H:%M:%S"), prefix, msg)

    def set_location(self, location_str):
        for i in range(10):
            try:
                geo_locator = GoogleV3()
                location = geo_locator.geocode(location_str)
                self.latitude, self.longitude, self.altitude = location.latitude, location.longitude, location.altitude
                self.orglatitude = self.latitude
                self.orglongitude = self.longitude
                self.log('Your given location: {}'.format(location.address.encode('utf-8')))
                self.log('lat/long/alt: {} {} {}'.format(self.latitude, self.longitude, location.altitude))
                return True
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                self.log('geo_locator exception ({}), retrying'.format(str(e)))
                time.sleep(1)
        return False

    def set_location_coords(self, new_lat, new_long, new_alt=0):
        self.latitude = new_lat
        self.longitude = new_long
        self.altitude = new_alt

    def get_location_coords(self):
        return f2i(self.latitude), f2i(self.longitude), f2i(self.altitude)

    def api_req(self, api_endpoint, access_token, *args, **kwargs):
        p_req = pokemon_pb2.RequestEnvelop()
        p_req.rpc_id = 1469378659230941192

        p_req.unknown1 = 2

        p_req.latitude, p_req.longitude, p_req.altitude = self.get_location_coords()

        p_req.unknown12 = 989

        if 'useauth' not in kwargs or not kwargs['useauth']:
            p_req.auth.provider = 'ptc'
            p_req.auth.token.contents = access_token
            p_req.auth.token.unknown13 = 14
        else:
            p_req.unknown11.unknown71 = kwargs['useauth'].unknown71
            p_req.unknown11.unknown72 = kwargs['useauth'].unknown72
            p_req.unknown11.unknown73 = kwargs['useauth'].unknown73

        for arg in args:
            p_req.MergeFrom(arg)

        protobuf = p_req.SerializeToString()

        r = self.session.post(api_endpoint, data=protobuf, verify=False)

        p_ret = pokemon_pb2.ResponseEnvelop()
        try:
            p_ret.ParseFromString(r.content)
        except Exception as e:
            #self.log("api_req: server response couldn't be decoded:{}".format(str(e)))
            self.log("api_req: server response couldn't be decoded")
            return None

        time.sleep(0.62)
        return p_ret

    def get_api_endpoint(self, access_token, api=API_URL):
        profile_response = None
        while not profile_response:
            profile_response = self.retrying_get_profile(access_token, api, None)
            if not hasattr(profile_response, 'api_url'):
                self.log("retrying_get_profile: get_profile returned no api_url, retrying")
                profile_response = None
                continue
            if not len(profile_response.api_url):
                self.log("api_endpoint: profile_response has no-len api_url, retrying")
                profile_response = None

        self.api_endpoint = 'https://%s/rpc' % profile_response.api_url
        return True

    def retrying_get_profile(self, access_token, api, useauth, *reqq):
        profile_response = None
        #while not profile_response:
        for i in xrange(10):
            profile_response = self.get_profile(access_token, api, useauth, *reqq)
            if not hasattr(profile_response, 'payload'):
                self.log("retrying_get_profile: get_profile returned no payload, retrying")
                profile_response = None
                continue
            if not profile_response.payload:
                self.log("retrying_get_profile: get_profile returned no-len payload, retrying")
                profile_response = None

        return profile_response

    def get_profile(self, access_token, api, useauth, *reqq):
        req = pokemon_pb2.RequestEnvelop()
        req1 = req.requests.add()
        req1.type = 2
        if len(reqq) >= 1:
            req1.MergeFrom(reqq[0])

        req2 = req.requests.add()
        req2.type = 126
        if len(reqq) >= 2:
            req2.MergeFrom(reqq[1])

        req3 = req.requests.add()
        req3.type = 4
        if len(reqq) >= 3:
            req3.MergeFrom(reqq[2])

        req4 = req.requests.add()
        req4.type = 129
        if len(reqq) >= 4:
            req4.MergeFrom(reqq[3])

        req5 = req.requests.add()
        req5.type = 5
        if len(reqq) >= 5:
            req5.MergeFrom(reqq[4])

        for i in xrange(10):
            try:
                response = self.api_req(api, access_token, req, useauth=useauth)
                if response:
                    return response
                #self.log("retrying_api_req: api_req returned None")
            except (InvalidURL, ConnectionError) as e:
                self.log("api_req: request error {}".format(str(e)))
            time.sleep(1)
        self.log("retrying_api_req: api_req couldn't be obtained, aborting...", 1)
        return None

    def login_ptc(self, username, password):
        self.log('login with name: {}'.format(username),3)
        head = {'User-Agent': 'Niantic App'}
        r = None
        while r is None:
            self.log('trying to get session...')
            r = self.session.get(LOGIN_URL, headers=head)
            self.log('got a session')
            try:
                jdata = json.loads(r.content)
            except ValueError as e:
                self.log("login_ptc: couldn't decode JSON")
                return None

        data = {
            'lt': jdata['lt'],
            'execution': jdata['execution'],
            '_eventId': 'submit',
            'username': username,
            'password': password,
        }
        r1 = self.session.post(LOGIN_URL, data=data, headers=head)

        ticket = None
        try:
            ticket = re.sub('.*ticket=', '', r1.history[0].headers['Location'])
        except Exception as e:
            self.log('login_ptc: '+str(r1.json()['errors'][0]))
            return None

        data1 = {
            'client_id': 'mobile-app_pokemon-go',
            'redirect_uri': 'https://www.nianticlabs.com/pokemongo/error',
            'client_secret': PTC_CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'code': ticket,
        }
        r2 = self.session.post(LOGIN_OAUTH, data=data1)
        access_token = re.sub('&expires.*', '', r2.content)
        access_token = re.sub('.*access_token=', '', access_token)

        self.access_token = access_token
        return True

    def get_heartbeat(self, api_endpoint, access_token, response):
        m4 = pokemon_pb2.RequestEnvelop.Requests()
        m = pokemon_pb2.RequestEnvelop.MessageSingleInt()
        m.f1 = int(time.time() * 1000)
        m4.message = m.SerializeToString()
        m5 = pokemon_pb2.RequestEnvelop.Requests()
        m = pokemon_pb2.RequestEnvelop.MessageSingleString()
        m.bytes = "05daf51635c82611d1aac95c0b051d3ec088a930"
        m5.message = m.SerializeToString()
        walk = sorted(self.get_neighbors())
        m1 = pokemon_pb2.RequestEnvelop.Requests()
        m1.type = 106
        m = pokemon_pb2.RequestEnvelop.MessageQuad()
        m.f1 = ''.join(map(encode, walk))
        m.f2 = "\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000\000"
        m.lat, m.long, _ = self.get_location_coords()
        m1.message = m.SerializeToString()
        response = self.get_profile(
            access_token,
            api_endpoint,
            response.unknown7,
            m1,
            pokemon_pb2.RequestEnvelop.Requests(),
            m4,
            pokemon_pb2.RequestEnvelop.Requests(),
            m5)
        try:
            payload = response.payload[0]
        except (AttributeError, IndexError):
            return
        heartbeat = pokemon_pb2.ResponseEnvelop.HeartbeatPayload()
        heartbeat.ParseFromString(payload)
        return heartbeat

    def get_neighbors(self):
        origin_cell = CellId.from_lat_lng(LatLng.from_degrees(self.latitude, self.longitude)).parent(15)
        walk = [origin_cell.id()]
        # 10 before and 10 after
        next_cell = origin_cell.next()
        prev_cell = origin_cell.prev()
        for i in range(10):
            walk.append(prev_cell.id())
            walk.append(next_cell.id())
            next_cell = next_cell.next()
            prev_cell = prev_cell.prev()
        return walk

    def run(self):
        for i in xrange(10):
            if not self.start_scan:
                self.log('start_scan is False, terminating', 1)
                continue
            self.log("launching...")
            if not self.set_location(self.location_str):
                self.log('unable to get location, terminating', 1)
                continue

            if not self.login_ptc(self.username, self.password):
                self.log('login attempt with username {} failed, terminating'.format(self.username), 1)
                continue
            self.log('RPC Session Token: {} ...'.format(self.access_token[:25]))

            if not self.get_api_endpoint(self.access_token):
                self.log('RPC-API server is unreachable or offline, terminating', 1)
                continue
            self.log('Received API endpoint: {}'.format(self.api_endpoint))

            profile_response = self.retrying_get_profile(self.access_token, self.api_endpoint, None)
            if profile_response is None or not profile_response.payload:
                self.log('Couldn\'t get player profile, terminating', 1)
                continue
            self.profile_response = profile_response
            payload = self.profile_response.payload[0]
            profile = pokemon_pb2.ResponseEnvelop.ProfilePayload()
            profile.ParseFromString(payload)

            self.log('Login successful with Username: {}'.format(profile.profile.username))

            if self.start_scan and self.restart_count < 10:
                self.pokemon_scan()
            else:
                self.log('restarted 10 times, something is very wrong... aborting', 1)
                break
        self.log('completed {} scans, but now startup failed 10 times, terminating thread'.format(self.scan_count), 1)
        self.need_restart = True

    def pokemon_scan(self):
        while self.do_scan:
            # reset to org position after scan
            self.log('Starting scan...')
            self.set_location_coords(self.orglatitude, self.orglongitude)
            origin_point = LatLng.from_degrees(self.latitude, self.longitude)
            pos = 1
            x = 0
            y = 0
            dx = 0
            dy = -1
            fresh_pokemon_list = []
            last_step_list_len = 0
            for steps in xrange(self.step_limit ** 2):
                if not self.do_scan:  # set by server, if new location is set
                    return
                parent = CellId.from_lat_lng(LatLng.from_degrees(self.latitude, self.longitude)).parent(15)
                h = self.get_heartbeat(self.api_endpoint, self.access_token, self.profile_response)
                hs = [h]
                seen = set([])
                for child in parent.children():
                    latlng = LatLng.from_point(Cell(child).get_center())
                    self.set_location_coords(latlng.lat().degrees, latlng.lng().degrees)
                    hs.append(self.get_heartbeat(self.api_endpoint, self.access_token, self.profile_response))
                self.set_location_coords(self.orglatitude, self.orglongitude)
                visible = []
                for hh in hs:
                    try:
                        for cell in hh.cells:
                            for wild in cell.WildPokemon:
                                wild_hash = wild.SpawnPointId + ':' + str(wild.pokemon.PokemonId)
                                if wild_hash not in seen:
                                    visible.append(wild)
                                    seen.add(wild_hash)
                    except AttributeError:
                        break
                for poke in visible:
                    pokemon_point = LatLng.from_degrees(poke.Latitude, poke.Longitude)
                    diff = pokemon_point - origin_point
                    diff_lat = diff.lat().degrees
                    diff_lng = diff.lng().degrees
                    direction = (('N' if diff_lat >= 0 else 'S') if abs(diff_lat) > 1e-4 else '') + (
                        ('E' if diff_lng >= 0 else 'W') if abs(diff_lng) > 1e-4 else '')

                    time_to_hidden = poke.TimeTillHiddenMs
                    new_entry = {'id': poke.pokemon.PokemonId,
                                 'name': self.pokemonJSON[str(poke.pokemon.PokemonId)],
                                 'direction': direction,
                                 'dist': int(origin_point.get_distance(pokemon_point).radians * 6366468.241830914),
                                 'time_visible': time_to_hidden,
                                 'time_found': datetime.now(),
                                 'latitude': poke.Latitude,
                                 'longitude': poke.Longitude}
                    self.wild_pokemon_list.append(new_entry)
                    fresh_pokemon_list.append(new_entry)

                # Scan location math
                if (-self.step_limit / 2 < x <= self.step_limit / 2) and (-self.step_limit / 2 < y <= self.step_limit / 2):
                    self.set_location_coords((x * 0.0025) + self.orglatitude, (y * 0.0025) + self.orglongitude)
                if x == y or (x < 0 and x == -y) or (x > 0 and x == 1 - y):
                    dx, dy = -dy, dx
                x, y = x + dx, y + dy
                #scan_completion = int(((steps+1 + (pos * .25) - .25) / self.step_limit ** 2) * 100)
                #self.log("Scan completion: {}%, found {} Pokemon".format(scan_completion,
                #        len(fresh_pokemon_list)-last_step_list_len))
                self.log("scan step {}/{} done, found {} new Pokemon".format(steps+1, self.step_limit ** 2, len(fresh_pokemon_list)-last_step_list_len))
                last_step_list_len = len(fresh_pokemon_list)

            self.last_scan_num_found = len(fresh_pokemon_list)
            self.last_scan_completed = datetime.now()
            if self.last_scan_num_found == 0:
                self.log('Scan completed but found no Pokemon! restarting', 1)
                break
            self.log("Scan completed, found {} pokemon. Next scan starts in 20 seconds.".format(len(fresh_pokemon_list)))
            self.scan_count += 1
            time.sleep(20)
        self.restart_count += 1
        self.run()

    def set_thread_to_die(self):
        self.do_scan = False
        self.start_scan = False

    def get_last_scan_num_found(self):
        return self.last_scan_num_found

    def get_current_location(self):
        return str(self.latitude)+', '+str(self.longitude)

    def get_origin_location(self):
        return str(self.orglatitude) + ', ' + str(self.orglatitude)

    def get_pokemon_list(self):
        seen = set([])
        pokemon_list = []
        for pokemon in self.wild_pokemon_list:
            # clean list from despawned
            if ms_dif_to_now(pokemon['time_found']) > pokemon['time_visible']:
                self.wild_pokemon_list.remove(pokemon)
                continue
            # remove duplicates
            poke_hash = (pokemon['latitude'], pokemon['longitude'])
            if poke_hash in seen:
                self.wild_pokemon_list.remove(pokemon)
                continue
            else:
                pokemon_list.append(pokemon)
                seen.add(poke_hash)
        return pokemon_list



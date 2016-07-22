import argparse
import json
import os
import logging
from flask import Flask, request, render_template
from Pokescanner import Pokescanner
from datetime import datetime

log = logging.getLogger('werkzeug')
#log.setLevel(logging.ERROR)
log.disabled = True

app = Flask(__name__, template_folder="templates")
scan_thread_list = []
active_thread_id = -1
settings = None
pokemonJSON = None
debug_mode = False


def time_left(ms):
    s = ms / 1000
    m, s = divmod(s, 60)
    return m, s


def time_to_hidden_formatted(time_in_ms):
    left = ' %02d minutes %02d seconds' % time_left(time_in_ms)
    left = left.replace('00 minutes ', '')
    return left


def ms_dif_to_now(start_time):
    dt = datetime.now() - start_time
    ms = (dt.days * 24 * 60 * 60 + dt.seconds) * 1000 + dt.microseconds / 1000.0
    return ms


def start_scanner(location_str):
    # start scanner
    # (threadID, name, username, password, location, step_limit)
    new_thread = Pokescanner(0, "scan_thread" + str(len(scan_thread_list)),
                             settings['username'], settings['password'],
                             location_str, settings['step_limit'], pokemonJSON)
    new_thread.daemon = True
    print('[+] starting scan thread...')
    new_thread.start()
    global active_thread_id
    active_thread_id += 1
    for thread in scan_thread_list:
        thread.set_thread_to_die()
    scan_thread_list.append(new_thread)


@app.route('/check')
def server_check():
    if len(scan_thread_list) < 1:
        return 'server has no scan thread! use locator to restart'
    output = '''active thread: {}<br>
    server restarts: {}<br>
        last scan found {} pokemon<br>
        last scan was completed by {}<br>'''.format(scan_thread_list[active_thread_id].name,
                                                scan_thread_list[active_thread_id].restart_count,
                                                scan_thread_list[active_thread_id].last_scan_num_found,
                                                scan_thread_list[active_thread_id].last_scan_completed)
    if scan_thread_list[active_thread_id].need_restart:
        output += '<p><b>Search thread says, it can\'t recover, starting new thread.</b></p>'
        start_scanner(settings['location'])
    return output


@app.route('/locations', methods=['GET', 'POST'])
def known_locations():
    if request.method == 'POST':
        if int(request.form['id']) in range(0, len(settings['locations'])):
            start_scanner('{},{}'.format(settings['locations'][int(request.form['id'])]['latitude'],
                                         settings['locations'][int(request.form['id'])]['longitude']))
        return 'setting location "{}" with id {}'.format(settings['locations'][int(request.form['id'])]['name'],
                                                         request.form['id'])
    else:
        return render_template('locations.html', locations=settings['locations'])


@app.route('/loc', methods=['GET', 'POST'])
def get_location():
    if request.method == 'POST':
        new_lati = request.form['latitude']
        new_long = request.form['longitude']
        new_alti = request.form['altitude']
        if new_alti is None:
            new_alti = 0
        print('[+] Killing thread and setting new Location latitude/longitude: {}/{}'.format(new_lati, new_long))
        #scan_thread_list[active_thread_id].set_thread_to_die()
        start_scanner(new_lati+', '+new_long)
        return '''
            <!doctype html>
            <title>testview</title>
            <meta http-equiv="refresh" content="5; URL=/finder">
            set as new values: [latitude, longitude, altitude]:<h1>
            ''' + str(new_lati) + ", " + str(new_long) + ", "+str(new_alti)+"</h1></html>"
    return render_template('get_loc.html')


@app.route('/finder')
def web_list():
    if scan_thread_list[active_thread_id].need_restart:
        output = '<meta http-equiv="refresh" content="5; URL=/finder">' \
                 '<p><b>Search thread says, it can\'t recover, starting new thread.</p>' \
                 '<br>wait for refresh</b>'
        start_scanner(settings['location'])
        return output
    if len(scan_thread_list) < 1:
        return 'server has no scan thread! use locator to restart'
    if 'desktop' in request.args:
        page_content = 'desktopmode<br><table border="1">'
    else:
        page_content = '<table border="1">'
    if len(scan_thread_list[active_thread_id].get_pokemon_list()) == 0:
        page_content = '<b>scan unfinished or nothing found...</b><br><table border="1">'
    poke_markers = []
    boring_markers = []
    for pokemon in scan_thread_list[active_thread_id].get_pokemon_list():
        time_to_hidden_tmp = int(pokemon['time_visible']) - int(ms_dif_to_now(pokemon['time_found']))
        html_line = '<td>'
        if 'desktop' not in request.args:
            html_line += '<a href=\'geo:0,0?q='+str(pokemon['latitude'])+','+str(pokemon['longitude']) + \
                     '('+pokemon['name']+')\'>'
        else:
            html_line += '<a href=\'https://maps.google.com/maps?q=loc:' + \
                str(pokemon['latitude']) + ',' + str(pokemon['longitude']) + '\'>'
        html_line += '<img height=\'60\' width=\'80\' src=\'static/icons/'+str(pokemon['id'])+'.png\'>' \
                     '</a></td>'
        html_line += '<td>' + \
                     time_to_hidden_formatted(time_to_hidden_tmp) + \
                     '</td>'
        html_line += '<td>' + str(pokemon['dist']) + ' m (' + pokemon['direction'] + ')</td>'
        if pokemon['id'] in settings['low_priority_ids']:
            boring_markers.append((html_line, pokemon['dist']))
        else:
            poke_markers.append((html_line, pokemon['dist']))

    poke_markers = sorted(poke_markers, key=lambda x: x[1])
    boring_markers = sorted(boring_markers, key=lambda x: x[1])
    for i in range(len(poke_markers)):
        page_content += '<tr>'+poke_markers[i][0]+'</tr>'
    page_content += '<tr><td></td><td><b>low priority</b></td><td></td></tr>'
    for i in range(len(boring_markers)):
        page_content += '<tr>' + boring_markers[i][0] + '</tr>'
    page_content += '</table>'
    page_content += '<br><a href=\'geo:0,0?q='+scan_thread_list[active_thread_id].get_origin_location()+'(origin)\'>used position</a>'
    if scan_thread_list[active_thread_id].get_last_scan_num_found() > 0:
        page_content += '<br>last scan found: ' + str(scan_thread_list[active_thread_id].get_last_scan_num_found())
    else:
        page_content += '<br>No complete scan'
    return page_content


@app.route('/idle')
def set_to_idle():
    print('[+] killing all threads, sending to idle')
    for thread in scan_thread_list:
        thread.set_thread_to_die()
    return '''
    all server threads are set to die, restart scanning <br><b><a href="/loc">here</a></b>'''


@app.before_first_request
def on_start_up():
    # load settings
    full_path = os.path.realpath(__file__)
    path, filename = os.path.split(full_path)

    parser = argparse.ArgumentParser()
    parser.add_argument("-st", "--step_limit", help="Steps", required=False)
    parser.add_argument("-d", "--debug", help="Debug Mode", action='store_true')
    parser.set_defaults(DEBUG=True)
    args = parser.parse_args()

    with open(path + '/settings.json') as infile:
        global settings
        settings = json.load(infile)
        print('[+] settings loaded from file')

    if args.debug:
        global debug_mode
        debug_mode = True
        print('[!] debug mode on')

    if 'locale' in settings:
        global pokemonJSON
        pokemonJSON = json.load(open(path + '/locales/pokemon.' + str(settings['locale']) + '.json'))
        print('[+] local set to ' + str(settings['locale']))
    else:
        pokemonJSON = json.load(open(path + '/locales/pokemon.de.json'))
        print('[+] local set to de')
    start_scanner(settings['location'])


@app.route('/sitemap')
def sitemap():
    return render_template('sitemap.html')


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=9090, debug=True, threaded=True)

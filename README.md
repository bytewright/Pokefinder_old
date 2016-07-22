<p align="center">
<img src="http://i.imgur.com/ZBZNBsf.png">
</p>

# PokemonGo Pokefinder

took codebase from AHAAAAAA... and rewrote most of it.<br>
The goal was, to have a dedicated server script with users on mobile phones and using as little mobile data volume as possible.<br>
The server consists of 2 scripts, pokefinder_server.py contains everything flask related, Pokescanner.py contains PGO client and does the scanning.<br>
<br>
Users connect to [host]/finder to see the list shown above. each icon is a geolink. When clicked, android phones will open Googlemaps app with a marker for the pokemon the user clicked. Opening the site is 3-5kB, opening gmaps with predownloaded maps shouldnt use data at all.<br>

Building off [Mila432](https://github.com/Mila432/Pokemon_Go_API)'s PokemonGo API, [tejado's additions](https://github.com/tejado/pokemongo-api-demo), [leegao's additions](https://github.com/leegao/pokemongo-api-demo/tree/simulation) and [Flask-GoogleMaps](https://github.com/rochacbruno/Flask-GoogleMaps). 

# Installation
`pip install -r requirements.txt` (from admin-level console)

# Usage
`python pokefinder_server.py`

settings.json has to be in same folder, see settings.json.example for content

# Notes
[host]/finder -> list seen above
[host]/loc -> enter new location
[host]/check -> see server status

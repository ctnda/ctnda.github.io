#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from imdb import IMDb
import json
# oppure jsonpickle???

# JSON snippets from https://github.com/hrishikeshsathe/IMDb-to-JSON
class JSONAttributes:
    title = ''
    duration = ''
    genre = []
    rating= 0.0
    description = ''
    actors = []
    seasons = []
    director = ''
    creators = []
    def __init__(self):
        self.title = ''
        self.duration = ''
        self.genre = []
        self.rating = 0.0
        self.description = ''
        self.actors = []
        self.director = ''
        self.creators = []

    def print_overview(self):
        print("Title: ",self.title)
        print("Duration: ",self.duration)
        print("Genre: ",self.genre)
        print("Rating: ",self.rating)
        print("Description: ",self.description)
        print("Creators: ",self.creators)
        print("Director: ",self.director)
        print("Actors: ",self.actors)

def write_json(json):

    """ write data into file as json object """

    file = open(json.title+'.json','w')
    file.write('{\n')
    file.write('"title":"'+json.title+'",\n')
    file.write('"duration":"'+json.duration+'",\n')
    file.write('"genre":[')
    file.write(','.join('"'+x+'"' for x in json.genre))
    file.write('],\n')
    file.write('"rating":"'+json.rating+'",\n')
    file.write('"description":"'+json.description+'",\n')
    file.write('"director":"'+json.director+'",\n')
    file.write('"creators":[')
    file.write(','.join('"'+x+'"' for x in json.creators))
    file.write('],\n')
    file.write('"actors":[')
    file.write(','.join('"'+x+'"' for x in json.actors))
    file.write('],\n')
    file.write('"seasons":[')
    file.write(','.join('['+episode_list_as_string(season)+']\n' for season in json.seasons))
    file.write(']\n}')
    file.close()
    print('Writing done')

#create json object. check class JSONAttributes(). it just contains variables to store values
json_temp = JSONAttributes()

# create an instance of the IMDb class
ia = IMDb()

# get a movie
movie = ia.get_movie('0060315')

# print the names of the directors of the movie
#print('Actors:')
for director in movie['director']:
    json_temp.director = director
    print(json.dump(json_temp))

# print the genres of the movie
print('Genres:')
for genre in movie['genres']:
    print(genre)


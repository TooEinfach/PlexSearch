from plexapi.server import PlexServer

baseurl = "http://10.0.0.208:32400"
token = "z4dreEx3u_kDThQiHvPP"
plex = PlexServer(baseurl, token)

# Search across the server
matches = plex.search("Jurassic Park", mediatype="movie")
print(len(matches))
for m in matches:
    print(m.title, m.year, m.ratingKey)

# Search inside a specific section by ID
section = plex.library.sectionByID(1)
matches = section.search("Jurassic Park")
print(len(matches))
for m in matches:
    print(m.title, m.year, m.ratingKey)
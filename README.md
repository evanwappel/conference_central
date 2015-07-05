In this Udacity project, we developed a cloud-based API server to support a provided conference organization application that exists on the web as well as a native Android application. The API supports the following functionality found within the app: user authentication, user profiles, conference information and various manners in which to query the data.

The Google App Engine application was used for developing the site.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.

Project id: festive-nova-91317

Deployed app can be accessed [here][7]


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool
[7]: https://festive-nova-91317.appspot.com

# Project Motivation and Overview

- Currently the Conference Central application is pretty limited
- Conferences have just name, description and date when the conference happens.
- Usually conferences have more than that - there are different sessions, with different speakers, maybe some of them happening in parallel!
- My task in this project is to add this functionality.

Some of the functionality will have well defined requirements, some of it will more open ended.
The frontend part of the app is not necessary to work on.
All added functionality will be testable via APIs Explorer.

## Tasks Required to Finish the Project

## Task 1: Add Sessions to a Conference

Overview

- Sessions can have speakers, start time, duration, type of session (workshop, lecture etc…), location.
- I will need to define the Session class and the SessionForm class, as well as appropriate Endpoints.
- Free to choose how I want to define speakers, eg just as a string or as a full fledged entity.

Endpoints

1. getConferenceSessions(websafeConferenceKey) - Given a conference, return all sessions
2. getConferenceSessionsByType(websafeConferenceKey, typeOfSession) - Given a conference, return all sessions of a specified type (eg lecture, keynote, workshop)
3. getSessionsBySpeaker(speaker)-- Given a speaker, return all sessions given by this particular speaker, across all conferences
4. createSession(SessionForm, websafeConferenceKey) -- open only to the organizer of the conference

Define Session class and SessionForm

In the SessionForm pass in:
* Session name
* highlights
* speaker
* duration
* typeOfSession
* date
* start time (in 24 hour notation so it can be ordered)

Ideally, create the session as a child of the conference. Explaination of design choices:


"""Explain in a couple of paragraphs your design choices for session and speaker implementation.


## Task 2: Add Sessions to User Wishlist

Overview

- Users should be able to mark some sessions that they are interested in and retrieve their own current wishlist.
- I am free to design the way this wishlist is stored.

Endpoints

addSessionToWishlist(SessionKey) -- adds the session to the user's list of sessions they are interested in attending

I can decide if they can only add conference they have registered to attend or if the wishlist is open to all conferences.

getSessionsInWishlist() -- query for all the sessions in a conference that the user is interested in


## Task 3: Work on indexes and queries

Create indexes

Make sure the indexes support the type of queries required by the new Endpoints methods.
Come up with 2 additional queries

Think about other types of queries that would be useful for this application. Describe the purpose of 2 new queries and write the code that would perform them.
Solve the following query related problem

Let’s say that you don't like workshops and you don't like sessions after 7 pm. How would you handle a query for all non-workshop sessions before 7 pm? What is the problem for implementing this query? What ways to solve it did you think of?


## Task 4: Add a Task

Overview

- When a new session is added to a conference, check the speaker.
- If there is more than one session by this speaker at this conference, also add a new Memcache entry that features the speaker and session names.
- I can choose the Memcache key.

Endpoints

getFeaturedSpeaker()
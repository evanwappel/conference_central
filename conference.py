
#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import FeaturedSpeakerForms

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

import logging
EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
MEMCACHE_FeaturedSpeaker_KEY = "FEATURED_SPEAKER"
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

SESSION_DEFAULTS = {
    "typeOfSession" : "Workshop",
    "start_time" : "09:00",
 }

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

SESSION_FIELDS =    {
            'TYPE': 'typeOfSession',
            'START_TIME': 'start_time',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)



# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        print "cf= ", cf
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        print "\n", "user= ", user, "\n" 
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        print "\n", "user_id= ", user_id, "\n"
        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        print "\n", "data= ", data, "\n"
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                print "\n", "df= ", df, "\n"
                print "\n", "data[df]= ", data[df], "\n"
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        print "\n", "p_key= ", p_key, "\n"
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        print "\n", "c_id= ", c_id, "\n"
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        print "\n", "c_key= ", c_key, "\n"
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

# createConference
    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

#updateConference
    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

# getConference
    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

# getConferencesCreated
    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        websafe_conference_key = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=websafe_conference_key).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % websafe_conference_key)

        # register
        if reg:
            # check if user already registered otherwise add
            if websafe_conference_key in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(websafe_conference_key)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if websafe_conference_key in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(websafe_conference_key)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=websafe_conference_key) for websafe_conference_key in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""

        # Task 3 Query 1:
        #q = Conference.query().\
        #    filter(Conference.city == "Palo Alto").\
        #    filter(Conference.topics == "Web Technologies")
        
        # Task 3 Query 2:
        q = Conference.query()
        q = q.filter(Conference.maxAttendees > 10)

        
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

# #--- new ---------------------------------------------------------------------------

# Task 1: Add Sessions to a Conference


# Task 1.1 Create session
    @endpoints.method(SESSION_POST_REQUEST, SessionForm, path='conference/{websafeConferenceKey}/sessions',
             http_method='POST', name='createSession')
    def createSession(self, request):
        """Task 1.4: Given a conference, create new session"""
        return self._createSessionObject(request)


    def _createSessionObject(self, request):
        """Create or update session object, returning SessionForm/request."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        print "\n", "data= ", data, "\n"

        # add default values for those missing (both data model & outbound Message)
        for df in SESSION_DEFAULTS:
            if data[df] in (None, []):
                data[df] = SESSION_DEFAULTS[df]
                setattr(request, df, SESSION_DEFAULTS[df])

        del data['websafeKey']
        del data['websafeConferenceKey']

        # generate Conference Key based on websafeConferenceKey
        # allocate session id based on conference key
        # generate Session key based on session id and session's parent key
        c_key = ndb.Key(urlsafe=request.websafeConferenceKey)
        print "\n", "c_key= ", c_key, "\n"
        s_id = Session.allocate_ids(size=1, parent=c_key)[0]
        print "\n", "s_id= ", s_id, "\n"
        s_key = ndb.Key(Session, s_id, parent=c_key)
        print "\n", "s_key= ", s_key, "\n"

        data['key'] = s_key
        print "\n", "data= ", data, "\n"
        session = Session(**data)
        print "\n", "session= ", session, "\n"
        session.put()

        # when a session is added, add a task to check for featured speaker

        # print "\n", "taskqueue_before= ", taskqueue
        # taskqueue.add( params = {'session_speaker' : session.speaker,
        #                          'session_name' : session.name,
        #                          'conf_key' : session.key.parent().urlsafe()},
        #                          url='/tasks/set_featured_speaker')
        # print "\n", "taskqueue_after= ", taskqueue

        # create Session, send email to organizer confirming
        # creation of Session & return (modified) SessionForm
        
        # Session(**data).put()
        # taskqueue.add(params={'email': user.email(),
        #     'sessionInfo': repr(request)},
        #     url='/tasks/check_featured_speaker'
        # )
        

        return self._copySessionToForm(session)



    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                setattr(sf, field.name, getattr(session, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, session.key.urlsafe())
        sf.check_initialized()
        return sf

# Task 1.2 Get conference sessions

    @endpoints.method(SESSION_GET_REQUEST, SessionForms, path='conference/{websafeConferenceKey}/sessions',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Task 1.1: Given a conference, return all sessions"""
        # create ancestor query for all key matches for this user
        sessions = Session.query(ancestor=ndb.Key(urlsafe=request.websafeConferenceKey))
        print "\n", "sessions= ", sessions, "\n"
        # return individual SessionForm object per Session
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# Task 1.3 Get sessions by type

    @endpoints.method(endpoints.ResourceContainer(
            message_types.VoidMessage,
            websafeConferenceKey=messages.StringField(1),
            typeOfSession=messages.StringField(2)),
            SessionForms, path='conference/{websafeConferenceKey}/sessions/type',
            http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
        """Task 1.2: Given a conference and a session type, return all sessions of a
         specified type (eg lecture, keynote, workshop)
        """
        sessions = Session.query(ancestor=ndb.Key(urlsafe=request.websafeConferenceKey))
        print "\n", "sessions= ", sessions, "\n"
        sessions = sessions.filter(Session.typeOfSession==request.typeOfSession)
        print "\n", "sessions= ", sessions, "\n"

        # return individual SessionForm object per Session
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# Task 1.4 Get sessions by speaker
    @endpoints.method(endpoints.ResourceContainer(
            message_types.VoidMessage,
            speaker=messages.StringField(1)),
            SessionForms, path='sessions/speaker',
            http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
        """Task 1.3: Given a speaker, retrun all sessions given by this particular speaker, across all conferences"""
        sessions = Session.query()
        print "\n", "sessions= ", sessions, "\n"
        sessions = sessions.filter(Session.speaker==request.speaker)
        print "\n", "sessions= ", sessions, "\n"

        # return individual SessionForm object per Session
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# Task 2: Add Sessions to User Wishlist

# 2.1 add session to wishlist

    @endpoints.method(endpoints.ResourceContainer(
            message_types.VoidMessage,
            websafeSessionKey=messages.StringField(1)), BooleanMessage,
            path='wishlist',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Task 2.1: Add the session to the user's list of sessions they are interested in attending"""
        return self._updateWishlist(request)
    
    @ndb.transactional
    def _updateWishlist(self, request, reg=True):
        """add session to wishlist"""

        #check to see if user is authoroized
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        print "\n", "user_id= ", user_id, "\n"
        profile_key = ndb.Key(Profile, user_id).get()
        print "\n", "profile_key= ", profile_key, "\n"

        # check to see if session exists
        websafe_session_key = request.websafeSessionKey
        print "\n", "websafe_session_key= ", websafe_session_key, "\n"
        try:
            session = ndb.Key(urlsafe=websafe_session_key).get()
        except Exception, e:
            print "\n", "e.__class__.__name__= ", e.__class__.__name__, "\n"
            if e.__class__.__name__ == 'ProtocolBufferDecodeError':
                raise endpoints.NotFoundException('session does not exist')

        print "\n", "session= ", session, "\n"

        # check to see if session is already on the wishlist
        if reg and websafe_session_key in profile_key.sessionKeysToAttend:
            raise ConflictException(
                "session has already been added to wishlist")

        profile_key.sessionKeysToAttend.append(websafe_session_key)

        # write things back to the datastore & return
        profile_key.put()
        return BooleanMessage(data=True)


# Task 2.2 query for all the sessions in a conference that the user is interested in

    @endpoints.method(message_types.VoidMessage, SessionForms,
        path='wishlist', http_method='GET', name='getSessionsInWishlist')

    def getSessionsInWishlist(self, request):
        """Task 2.2: query for all the sessions in a session that the user is interested in"""
        prof = self._getProfileFromUser() # get user Profile
        session_keys = [ndb.Key(urlsafe=websafe_session_key) for websafe_session_key in prof.sessionKeysToAttend]
        print "\n", "session_keys= ", session_keys, "\n"
        sessions = ndb.get_multi(session_keys)
        print "\n", "sessions= ", sessions, "\n"

        # return individual SessionForm object per Session
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )


# Task 3 query problem: filter playground for sessions
    @endpoints.method(message_types.VoidMessage, SessionForms,
                path='filterPlayground_session',
                http_method='GET', name='filterPlayground_session')
    def filterPlayground_session(self, request):
        """Filter Playground for sessions"""

        q = Session.query().filter(Session.typeOfSession != "Workshop")
        items_modified = []
        items=[self._copySessionToForm(sess) for sess in q]
        s2 = "start_time"
        for x in range(0,len(items)):
            string = str(items[x])
            offset = str(items[x]).find(s2)+14
            length = 2
            sliced = string[offset:offset+length]
            if sliced.isdigit() == True:
                if int(sliced) < 19:
                    items_modified.append(items[x])

        return SessionForms(items=items_modified)


    
# Task 4 - add a task


    @staticmethod
    def _setFeaturedSpeaker(session_speaker, session_name, conf_key):
        """Set featured speaker in memcache"""
        # query sessions and check if a speaker appears more than once
        d = memcache.get(MEMCACHE_FeaturedSpeaker_KEY)
        if not d:
            d = {}
        if session_speaker not in d:
            q = Session.query(ancestor=ndb.Key(urlsafe=conf_key))
            q = q.filter(Session.speaker==session_speaker).fetch()
            if len(q) >= 2:
                items = [ item.name for item in q]
                d[session_speaker] = items
                ret = memcache.set(MEMCACHE_FeaturedSpeaker_KEY, dict(d))

        else:
            d[session_speaker].append(session_name)
            ret = memcache.replace(MEMCACHE_FeaturedSpeaker_KEY, dict(d))



# # Memcache ---------------------------------------------------------------
    @endpoints.method(message_types.VoidMessage, FeaturedSpeakerForms,
            path='speaker',
            http_method='GET', name='getFeaturedSpeaker')

    def getFeaturedSpeaker(self, request):
        """Task 4: Return featured speaker and session name from memcache."""
        d = memcache.get(MEMCACHE_FeaturedSpeaker_KEY)
        print "d= ", d
        if not d:
            print "nothing in memcache"
            return FeaturedSpeakerForms()

        items = []
        for k, v in d.iteritems():
            fs = FeaturedSpeakerForm()
            fs.speaker = k
            fs.session_names = [StringMessage(data=s) for s in v]
            items.append(fs)

        return FeaturedSpeakerForms(items=items)




api = endpoints.api_server([ConferenceApi]) # register API

from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, join_room, leave_room
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.exceptions import BadRequest
from datetime import datetime
from user import User
from db import get_user, save_user, save_room, add_room_members, get_rooms_for_user, get_room, is_room_member, get_room_members, is_room_admin, update_room, remove_room_members, save_message, get_messages
from pymongo.errors import DuplicateKeyError
from bson.json_util import dumps

app = Flask(__name__) # Creating Flask app object
app.secret_key = "my secret key" # check later the correct way to define a secret key.
socketio = SocketIO(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app) # Connected Login Manager with Flask Application Object.

@app.errorhandler(BadRequest)
def handle_bad_request(e):
    return 'Bad Request', 400

# Creating two pages of the chat application:
# Page 1: Choose Chat Room (homepage)
# Page 2: Inside the Chosen Chat-Room where conversation with other users can be had.

@app.route('/')
def home_page():
    rooms = []
    if current_user.is_authenticated:
        rooms = get_rooms_for_user(current_user.username)
    return render_template("index.html", rooms=rooms)

@app.route('/login', methods=['GET', 'POST'])
def login():
    
    if current_user.is_authenticated:
        return redirect(url_for('home_page'))
    message = ''
    if request.method == 'POST':    
        username = request.form.get('username')
        password_input = request.form.get('password')
        user = get_user(username)
        
        if user and user.check_password(password_input):
            login_user(user)
            return redirect(url_for('home_page'))
        else:
            message = 'Failed to login!'
        
    return render_template('login.html', message=message)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('home_page'))

@app.route('/create-room', methods=['GET', 'POST'])
@login_required
def create_room():
    if request.method == 'POST':
        room_name = request.form.get('room_name')
        usernames = [username.strip() for username in request.form.get('members').split(',')]
        
        if len(room_name) and len(usernames):
            room_id = save_room(room_name, current_user.username)
            
            if current_user.username in usernames:
                usernames.remove(current_user.username)
            add_room_members(room_id, room_name, usernames, current_user.username)
            return redirect(url_for('view_room', room_id = room_id))
        else:
            message = "Failed to create room" 
    return render_template('create_room.html')

@app.route('/signup', methods = ['GET','POST']) # 'GET' request is used to give out the form for registration and in the POST request you get the response of the form
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('home_page'))
    
    message = ''
    if request.method == 'POST':    
        username = request.form.get('username')
        email = request.form.get('email')
        password_input = request.form.get('password')
        try:
            save_user(username, email, password_input)
            return redirect(url_for('login'))
        except DuplicateKeyError:
            message = "User already exists"
        
        
    return render_template('signup.html', message=message)

@app.route('/rooms/<room_id>/')
@login_required
def view_room(room_id):
    room = get_room(room_id)
    if room and is_room_member(room_id, current_user.username):
        room_members = get_room_members(room_id)
        messages = get_messages(room_id)
        return render_template('view_room.html', username=current_user.username, room=room, room_members=room_members, messages=messages)
    else:
        return "Room not found", 404
    
@app.route('/rooms/<room_id>/messages/')
@login_required
def get_older_messages(room_id):
    room = get_room(room_id)
    if room and is_room_member(room_id, current_user.username):
        page = int(request.args.get('page', 0))
        messages = get_messages(room_id, page)
        return dumps(messages)
    else:
        return "Room not found", 404

@app.route('/rooms/<room_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_room(room_id):
    room = get_room(room_id)
    if room and is_room_admin(room_id,  current_user.username):
        existing_room_members = [member['_id']['username'] for member in get_room_members(room_id)]
        room_members_str = ",".join(existing_room_members)
        message=''
        if request.method == 'POST':
            room_name = request.form.get('room_name')
            room['name'] = room_name
            update_room(room_id, room_name)
            new_members = [username.strip() for username in request.form.get('members').split(',')]
            members_to_add = list(set(new_members) - set(existing_room_members))
            members_to_remove = list(set(existing_room_members) - set(new_members))
            if len(members_to_add):
                add_room_members(room_id, room_name, members_to_add, current_user.username)
            if len(members_to_remove):
                remove_room_members(room_id, members_to_remove)
            message = 'Room edited successfuly.'   
            room_members_str = ",".join(new_members)
        room_members_str = ",".join(existing_room_members)
        return render_template('edit_room.html', room=room, room_members_str=room_members_str, message = message)
    else:
        return "Room not found", 404
    
@socketio.on('join_room')
def handle_join_room_event(data):
    app.logger.info("{} has joined the room {}".format(data['username'], data['room']))
    join_room(data['room'])
    socketio.emit('join_room_announcement', data) # Send announcement to other clients
    
@socketio.on('send_message')
def handle_send_message_event(data):
    app.logger.info("{} has sent message to the room {}: {}".format(data['username'], data['room'], data['message']))
    
    data['created_at'] = datetime.now().strftime("%d %b, %H:%M")
    join_room(data['room'])
    save_message(data['room'], data['message'], data['username'])
    socketio.emit('receive_message', data, room= data['room'])
    
@socketio.on('leave_room')
def handle_leave_room_event(data):
    app.logger.info("{} has left the room {}".format(data['username'], data['room']))
    leave_room(data['room'])
    socketio.emit('leave_room_announcement', data, room=data['room'])
    
@login_manager.user_loader
def load_user(username):
    return get_user(username)
    

if __name__ == '__main__':
    #app.run(debug=True) # passing debug=True argument allows real-time update in interface to changes in the code.
    #socketio.run(app, debug=True)
    socketio.run(app, debug=True, ssl_context='adhoc')

from flask import Flask, render_template, url_for, request, redirect, flash, session
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
from firebase import firebase
from datetime import datetime, timedelta
import requests, json, pytz

# app initialisation
app = Flask(__name__, static_url_path='/static')
app.config['SECRET_KEY'] = 'vasundharashukla070999'

# admin id and password
admin_id = 'adminadmin'
admin_pass = 'iamadmin'

# setting timezone
tz = pytz.timezone('Asia/Kolkata')

# flask_mail config
mail_settings = {
    "MAIL_SERVER": 'smtp.gmail.com',
    "MAIL_PORT": 465,
    "MAIL_USE_TLS": False,
    "MAIL_USE_SSL": True,
    "MAIL_USERNAME": '<your gmail id>',
    "MAIL_PASSWORD": '<gmail password>'
}

app.config.update(mail_settings)
mail = Mail(app)

# getting country phone codes from json file
jsonfile = open('codes.json', encoding = "utf-8")
country_codes = json.load(jsonfile)
jsonfile.close()

# running the task scheduler
# the scheduler enables us to send emails and sms in the background
scheduler = BackgroundScheduler({'apscheduler.timezone': 'Asia/Calcutta'})
scheduler.start()

# initialising the firebase database
firebase = firebase.FirebaseApplication('https://entry-app-ff962.firebaseio.com/', None)

# method to send messages using way2sms api.
def send_message(msg, phone):

    # config sms api
    req_params = {
    'apikey': '<way2sms api key>',
    'secret': '<way2sms secret>',
    'usetype': 'stage',
    'phone': phone,
    'message': msg,
    'senderid': '1234'
    }

    # sending sms through api. returning the response
    return requests.post('https://www.way2sms.com/api/v1/sendCampaign', req_params)

# method to send emails using Flask_mail
def send_mail(message, email):
    with app.app_context():
        msg = Message(subject="check-in/check-out notification",
                      sender=app.config.get("MAIL_USERNAME"),
                      recipients=email, # replace with your email for testing
                      body=message)
        mail.send(msg)


# parent method to generate messages and call the send_message and send_mail functions
def send_check_in_message(host_det, user_det):
    m1 = f'Check-In Recorded.\nName: {user_det["name"]}\nIn-Time: {user_det["time-in"]}\nPhone: {user_det["phone"]}\nEmail: {user_det["email"]}\n'
    m2 = f'Out Time: {user_det["time-out"]}'
    message = m1+m2
    email, phone = host_det['email'], host_det['phone']
    send_message(message, phone)
    send_mail(message, [email])

# job scheduler. schedules email and sms jobs to be executed at given time.
def sched_job(date, user_det, host_det, vis):

    time, email, phone = user_det['time-out'], user_det['email'], user_det['phone']
    m1 = f'You have been checked out.\nName: {user_det["name"]}\nIn-Time: {user_det["time-in"]}\nOut Time: {user_det["time-out"]}\nPhone: {user_det["phone"]}\n'
    m2 = f'Host Name: {host_det["name"]}\nAddress: {host_det["address"]}.\nThanks for your visit!\n'
    message = m1+m2

    # getting time and date
    tm = datetime.strptime(date+" "+time, '%Y-%m-%d %H:%M')

    # adding new job to scheduler
    job = scheduler.add_job(scheduled, trigger='date', next_run_time = tm, args = [message, phone, email, date, vis,])
    return job

# this is the method we schedule.
# as soon as the scheduler starts executing a job
# it calls this method which then call the send_message and sen_mail methods.
def scheduled(message, phone, email, date, vis):

    # checking if the vistor has already checked out if no then perform check out.
    res = firebase.get(f'/users/{phone}/{date}/{vis}/', None)
    if not res['out']:
        res['out'] = 1
        send_mail(message, [email])
        send_message(message, phone)
        res = firebase.patch(f'/users/{phone}/{date}/{vis}/', res)

# route to check-in or home page
@app.route('/', methods = ['GET'])
@app.route('/check-in', methods = ['GET', 'POST'])
def check_in():
    if request.method == 'POST':
        l = ['email', 'name', 'time-in', 'time-out', 'host-phone']
        user_det, d = dict(), dict()

        # getting form values
        for i in l: user_det[i] = request.form[i]
        
        user_det['phone'] = request.form['code'] + request.form['phone']
        chih, chim = user_det['time-in'][:2], user_det['time-in'][3:]
        choh, chom = user_det['time-out'][:2], user_det['time-out'][3:]
        dtti = datetime.now()
        dtti = dtti.astimezone(tz)

        nwh, nwm = dtti.hour, dtti.minute

        # validating time
        if chih > choh or chih==choh and chim >= chom:
            flash('Check out time should be greater than check in time!'.upper())
            return redirect(url_for('check_in'))
        
        elif int(chih) < nwh or int(chih) == nwh and int(chim) < nwm and nwm - int(chim) > 5:
            flash('Check In time cannot be in the past!'.upper())
            return redirect(url_for('check_in'))

        # validating host phone number
        elif user_det['host-phone'] == "null":
            flash('Host not selected!'.upper())
            return redirect(url_for('check_in'))

        # verifying if the phone code is correctly enteres
        elif request.form['code'] == "null":
            flash('Country Code Cannot be left blank!'.upper())
            return redirect(url_for('check_in'))

        # validating phone number
        elif len(user_det['phone']) != 13:
            flash('Invalid Mobile Number! Mobile number should have exactly 10 digits.'.upper())
            return redirect(url_for('check_in'))
        
        try:
            phone = user_det['phone']
            result = firebase.get(f'users/{phone}/', None)
            # get data from database
            # if user has previously checked in
            # do not store his name and email again
            # creating a new index to just store time and host details
            if result is None or result["email"] != user_det["email"] or result["name"] != user_det["name"]:
                for i in l[:2]: d[i] = user_det[i]
                res = firebase.patch(f'/users/{phone}/', d)
                
            d = dict()
            for i in l[2:]: d[i] = user_det[i]
            
            date = datetime.strftime(dtti.date(), '%Y-%m-%d')
            time = f'{dtti.hour}:{dtti.minute}:{dtti.second}' 
            d['at'], d['out'], result = time, 0, []
            result = firebase.get(f'users/{phone}/{date}/', None)
            # getting user visits for the date
            
            vis = 0
            if result is None:
                r = {date: [d]}                
            else:                
                result.append(d)
                vis = len(result)-1
                r = {date: result}
                
            res = firebase.patch(f'/users/{phone}/', r)
            # getting host details
            host_det = firebase.get(f'/host/{user_det["host-phone"]}', None)
            if host_det is None: raise Exception
            
            host_det['phone'] = user_det['host-phone']

            # sending messages and scheduling job
            send_check_in_message(host_det, user_det)            
            job = sched_job(date, user_det, host_det, vis)
            
            return render_template('check-in.html', flg = 1, vals = user_det, host = host_det['name'])
        
        except Exception as e:
            flash(e)
            return render_template('check-in.html', flg=-1)

    # getting host details for select dropdown values
    host_names = firebase.get('/host/', None)
    hosts = []
    if host_names is not None:
        hosts = [(k, v['name']) for k, v in host_names.items()]
    return render_template('check-in.html', flg=0, hosts = hosts, codes = country_codes)

# route for check-out page
@app.route('/check-out', methods = ['GET', 'POST'])
def check_out():

    if request.method == 'POST':
        try:
            l = ['time-out', 'phone']
            details = dict()

            # getting form details
            for i in l:
                if i == 'phone':
                    details[i] = request.form['code'] + request.form[i]
                else:
                    details[i] = request.form[i]

            # checking if mobile number exists
            # if no there are no checkins
            date = datetime.strftime(datetime.now(), '%Y-%m-%d')
            get_vals = firebase.get(f'/users/{details["phone"]}/{date}/', None)

            if get_vals is None:
                flash("You have no check in's OR you have entered wrong mobile number. Please enter the mobile number used at the time of check in.")
                return redirect(url_for('check_out'))

            # if any of the out keys is 1
            # check out for that entry
            # checked from latest to oldest entries
            
            vis = -1
            for i in range(len(get_vals) - 1, -1, -1):
                if get_vals[i]['out'] == 0:
                    vis = i
                    break
            # if no entries is one user is assumed to have already checked out.
            if vis == -1:
                flash("No check in's")
                return redirect(url_for('check_out'))

            # performing check out operation
            res = get_vals[vis]
            res['out'] = 1
            res['time-out'] = details['time-out']
            res = firebase.patch(f'/users/{details["phone"]}/{date}/{vis}/', res)
            email = firebase.get(f'/users/{details["phone"]}/email', None)
            name =  firebase.get(f'/users/{details["phone"]}/name', None)
            host_det = firebase.get(f'/host/{res["host-phone"]}/', None)
            host_name, host_add = host_det["name"], host_det["address"]
            
            # sending messages and mails after checkout
            m1 = f'You have been checked out.\nName: {name}\nIn-Time: {res["time-in"]}\nOut Time: {res["time-out"]}\nPhone: {details["phone"]}\n'
            m2 = f'Host Name: {host_name}\nAddress: {host_add}.\nThanks for your visit!\n'
            message = m1+m2
            send_mail(message, [email])
            send_message(message, details['phone'])
            
            return render_template('check-out.html', flg=1)

        except Exception as e:
            flash(e)
            return render_template('check-out.html', flg=-1)
                
    return render_template('check-out.html', flg = 0, codes = country_codes)

# route for admin-login page
@app.route('/admin', methods = ['GET', 'POST'])
def admin_login():
    if request.method == 'POST':

        # getting login form data
        user = request.form['user']
        pwd = request.form['pass']

        # validating username and password
        # if valid, creating session variable and login the user
        if user == admin_id and pwd == admin_pass:
            session['logged-in'] = 1
            return redirect(url_for('register_host'))
        
        # if not redirecting back to login page
        else:
            flash('LOGIN FAILED!!!')
            return redirect(url_for('admin_login'))

    return render_template('admin-login.html', flg = 0)

# route for admin-logout
@app.route('/admin-logout', methods = ['GET'])
def admin_logout():

    # if session does not exist
    # bar access from the link
    # otherwise logout and redirect to
    # check-in/home page
    
    if session.pop('logged-in', None):
        flash('LOGGED OUT!')
    else:
        flash('NOT AUTHORIZED TO ACCESS THIS PAGE!')

    return redirect(url_for('check_in'))

# route for new-host page
@app.route('/new-host', methods = ['GET', 'POST'])
def register_host():

    # if no session exists bar access
    # redirecting to homepage
    if not session.pop('logged-in', None):
        flash('NOT AUTHORIZED TO ACCESS THIS PAGE!')
        return redirect(url_for('check_in'))
    
    session['logged-in'] = 1
    if request.method == 'POST':
        l = ['email', 'name', 'address', 'phone']
        details = dict()

        # getting form data
        for i in l:
            if i == 'phone':
                details[i] = request.form['code'] + request.form[i]
            else:
                details[i] = request.form[i]

        # verifying phone code for null value
        if request.form['code'] == "null":
            flash('Country Code Cannot be left blank!'.upper())
            return redirect(url_for('register_host'))

        # validating phone for length
        elif len(details['phone']) != 13:
            flash('Invalid Mobile Number! Mobile number should have exactly 10 digits.'.upper())
            return redirect(url_for('register_host'))

        # verifying if a host already exists
        # with same phone number or email
        # if yes redirect back to reguster page
        
        check = firebase.get(f'/host/', None)
        ckpt = 1
        if check == None:
            check = dict()
        for k, v in check.items():
            if k == details['phone']:
                ckpt = -1
                break

            if details['email'] == v['email']:
                ckpt = 0
                break

        if ckpt == 0:
            flash('Email ID already exists. Enter another email id.'.upper())
            return redirect(url_for('register_host'))

        elif ckpt == -1:
            flash('Phone Number already exists. Enter another phone number.'.upper())
            return redirect(url_for('register_host'))

        # creating new host because everything is fine, :)
        else:
            d = dict()
            for i, j in details.items():
                if i!='phone':
                    d[i] = j
                    
            # creating and informing new host about their creation. I just created you man! God feels... xD.
            res = firebase.patch(f'/host/{details["phone"]}/', d)
            send_message(f'Dear {details["name"]},\nYou have been registered as host at EMAIL NOTIFIER.\n-Admin', details["phone"])
            send_mail(f'Dear {details["name"]},\nYou have been registered as host at EMAIL NOTIFIER.\n-Admin', [details["email"]])
            return render_template('new-host.html', flg=1)
                        
    return render_template('new-host.html', flg=0, codes = country_codes)
    

if __name__ == "__main__":
    app.run(debug=True)

    # infinite loop to keep the app alive on heroku servers
    # so that the scheduler does not shutdown
    # as heroku sleeps if the app remains inactive for a long time.
    # to prevent that we run a infinte loop in the background.
    # Lazy guy heroku. :p
    try:
        while True:
            time.sleep(5)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

# Thanks for reading till the end. :) <3.


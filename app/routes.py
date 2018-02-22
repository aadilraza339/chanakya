import random, string

from app import app, exotel
from flask import render_template, request, session, flash, redirect, url_for
from datetime import datetime
from app import repos
from app.helper_methods import ( get_random_string,
                                 calculate_marks_and_dump_data,
                                 get_time_remaining, get_question_set
                                )

global_questions = False
################### VIEWS #######################
def go_to_page(code=None):
    return redirect(url_for(session.get('page')))

@app.before_request
def before_request():
    if request.endpoint not in ("create_question", "exotel_enroll_for_test"):
        if not session.get("page"):
            session["page"] = "enter_enrolment"
            return go_to_page()

@app.route('/')
@app.route('/enter-enrolment')
def enter_enrolment():
    if session.get("page") == "enter_enrolment":
        enrolment_key = request.args.get("enrolment_key")
        if enrolment_key and repos.is_valid_enrolment(enrolment_key):
            session["enrolment_key"]   = enrolment_key
            session["page"] = "before_test"
        else:
            return render_template("enter_enrolment.html")
    return go_to_page()

@app.route('/before-test', methods=["GET", "POST"])
def before_test():
    if session.get("page") == "before_test":
        if request.method == "GET":
            return render_template("before_test.html")
        elif request.method == "POST":
            if repos.can_start_test(session["enrolment_key"]):
                session["page"] = "test"
            else:
                return "Unable to Start your Test, Contact Navgurukul", 400
    return go_to_page()

@app.route('/test', methods=['GET', 'POST'])
def test():
    print("test was called")
    if session.get("page") == "test":
        if not session.get("questions"):
            global global_questions
            if not global_questions:
                global_questions = repos.get_all_questions() #very slow
            questions = global_questions
            session["questions"] = questions
            session["test_start_time"]  = datetime.utcnow()
            session['total_time_shown'] = 0
            session["test_score"]       = 0
        time_remaining = get_time_remaining(session.get("test_start_time")) - session['total_time_shown']
        if time_remaining > 0:
            session['set_name'], session['is_last_set'], question_set, time_to_show = get_question_set(session.get('questions'), time_remaining)
            session['last_time_shown']  = time_to_show 
            print(session['set_name'], time_to_show)
            session['question_set']     = question_set
            return render_template("test.html", question_set=question_set, time_remaining=time_to_show)
        else:
            t = str(time_remaining)
            return "timer has expired, call Navgurukul for more details.%s" %t
    return go_to_page()

@app.route("/end", methods=["GET", "POST"])
def end():
    if session.get("page") == "test" and request.method == "POST":
        question_set = session.get("question_set")
        other_details = {
            "start_time":session.get("test_start_time"),
            "submit_time":datetime.utcnow(),
            "enrolment_key":session.get("enrolment_key"),
            "set_name": session.get("set_name")
        }
        session['total_time_shown'] += session['last_time_shown']
        data_dump = calculate_marks_and_dump_data(question_set, request.form)
        repos.save_test_result_and_analytics(data_dump, other_details)
        session["test_score"] += data_dump.get("total_marks")
        print(session['is_last_set'], session["page"])
        if session.get('is_last_set'):
            session["page"] = "ask"
    return redirect(url_for('test'), code=303)

@app.route("/ask", methods=['GET', 'POST'])
def ask():
    if session.get("page") == "ask":
        return render_template("ask_details.html")
    return go_to_page()

@app.route("/send-details", methods=['GET', 'POST'])
def send_details():
    if session.get("page") == "ask" and request.method=="POST":
            student_details = repos.can_add_student(session.get("enrolment_key"), request.form)
            if student_details:
                repos.add_to_crm(student_details, session)
                session.clear()
                return render_template("thanks.html")
            else:
                flash("Unable to Save Your Details, Contact Navgurukul.")
    return go_to_page()

@app.route("/ask", methods=['GET', 'POST'])

@app.route("/create-question", methods=["GET", "POST"])
def create_question():
    #no-authentication: dangerous ??
    t1 = datetime.now()
    if request.method == "GET":
        return render_template("create_question.html")
    elif request.method == "POST":
        en_question_text = request.form.get("en_question_text") 
        hi_question_text = request.form.get("hi_question_text") 
        question_type = request.form.get("question_type") 
        difficulty = request.form.get("difficulty") 
        category = request.form.get("category") 

        option_1 = request.form.get("option_1") 
        option_2 = request.form.get("option_2") 
        option_3 = request.form.get("option_3") 
        option_4 = request.form.get("option_4") 
        question_details =      {
                                    "en_question_text":en_question_text,
                                    "hi_question_text":hi_question_text,
                                    "question_type":question_type,
                                    "difficulty":difficulty,
                                    "category":category,
                                    "options":[option_1, option_2, option_3, option_4]
                                }
        is_question_created, error = repos.create_question(question_details)
        if is_question_created:
            flash("question is created, successfully")
            return redirect(url_for("create_question"))
        else:
            flash("question not created: %s" %error)
            return redirect(url_for("create_question"))

######## APIS can be configured as another microservice ?? ########
############ REST APIS ##############

@app.route("/exotel_enroll_for_test")
def exotel_enroll_for_test():
    # get the student mobile number
    student_mobile = request.args.get("CallFrom")
    if not student_mobile:
        return "ERROR", 500
    if student_mobile[0] == "0":
        student_mobile = student_mobile[1:]

    # generate an enrolment number for the student
    enrolment_key =  get_random_string()
    enrolment_key = repos.add_enrolment_key(enrolment_key, student_mobile)
    if not enrolment_key:
        return "ERROR", 500
    
    # send an SMS with the enrolment number
    #TODO: Implement the real message when we buy exotel.
    message = app.config.get("TEST_ENROLL_MSG").format(test_url=enrolment_key)
    # test_message = "This is a test message being sent using Exotel with a (hello) and (123456789). If this is being abused, report to 08088919888"
    exotel.sms(app.config.get("EXOTEL_NUM_SMS"), student_mobile, message)

    return "SUCCESS", 200


####################
## Zoho Web Hooks ##
####################

@app.route("/zoho_crm/on_potential_stage_change")
def on_crm_potential_stage_edit():
    
    # get the student details
    enrolment_key = request.args.get("enrolment_key")
    student_mobile = request.args.get("mobile")
    stage = request.args.get("stage")

    # figure out the next actions that need to be taken
    stage_actions = app.config['POTENTIAL_STUDENT_STAGE_NOTIFS']
    actions = stage_actions.get(stage)
    if actions is None:
        return "No action needs to be taken", 200
    
    # trigger the sms
    if actions.get("sms"):
        #TODO: Implement the real message when we buy exotel.
        message = app.config.get("TEST_ENROLL_MSG")
        test_message = "This is a test message being sent using Exotel with a (hello) and (123456789). If this is being abused, report to 08088919888"
        exotel.sms(app.config.get("EXOTEL_NUM_SMS"), student_mobile, test_message)

    # trigger the outbound call
    if actions.get("exotel_obd_id"):
        #TODO: Need to integrate this when we add the outbound flows in exotel.
        pass

    # trigger an email
    if actions.get("referral_email_template"):
        #TODO: Need to integrate this when we add this support in the platform.
        pass

    return "All the required actions are already taken.", 200
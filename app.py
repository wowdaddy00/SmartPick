import os, json, random
from flask import Flask, render_template, request
from collections import Counter
import datetime
import requests
import itertools

app = Flask(__name__)

# Function to log events for administration
def log_event(event, detail=None):
    log = {
        "dt": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "event": event,
        "detail": detail or {}
    }
    logfile = "admin_log.json"
    try:
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")
    except Exception as e:
        print("로그 기록 오류:", e) # Print error to console, as alert() is not allowed

# Function to fetch the latest winning lotto numbers (excluding bonus)
def fetch_latest_lotto_number():
    url = "https://dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
    latest = get_latest_round()
    resp = requests.get(url + str(latest))
    data = resp.json()
    
    nums = []
    # Check if all winning numbers (drwtNo1 to drwtNo6) exist and are integers
    for i in range(1, 7):
        key = f'drwtNo{i}'
        if key not in data or not isinstance(data[key], int):
            return None, None # Return None if winning numbers are not available
        nums.append(data[key])
    return latest, nums

# Function to get the latest lottery round number
def get_latest_round():
    # Search backwards from a high number to find the latest valid round
    url = "https://dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
    for drw in range(1200, 1000, -1): # Search from 1200 down to 1001
        resp = requests.get(url + str(drw))
        data = resp.json()
        # Return round number if data is successful and all 6 winning numbers are integers
        if data.get('returnValue') == 'success' and all(isinstance(data.get(f'drwtNo{i}'), int) for i in range(1, 7)):
            return drw
    return None

# Function to fetch latest lotto numbers with bonus number
def fetch_latest_lotto_with_bonus():
    latest = get_latest_round()
    url = "https://dhlottery.co.kr/common.do?method=getLottoNumber&drwNo="
    resp = requests.get(url + str(latest))
    data = resp.json()
    nums = [data[f'drwtNo{i}'] for i in range(1, 7)]
    bonus = data['bnusNo']
    return latest, nums, bonus

# Function to generate combinations for 2nd and 3rd rank numbers
def make_rank2_3(nums, bonus):
    # Get all combinations of 5 numbers from the 6 winning numbers
    combis = list(itertools.combinations(nums, 5))
    rank2 = []
    rank3 = []
    for c in combis:
        # If the combination includes the bonus number, it's a 2nd rank equivalent
        if bonus in c:
            rank2.append(tuple(sorted(c)))
        else:
            # Otherwise, it's a 3rd rank equivalent (5 matching, no bonus)
            rank3.append(tuple(sorted(c)))
    return rank2, rank3

# Paths to the JSON files storing winning numbers data
BASE_DIR = os.path.dirname(__file__)
WINNING1_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_full.json')
WINNING2_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_rank2.json')
WINNING3_PATH = os.path.join(BASE_DIR, 'static', 'winning_numbers_rank3.json')

# Function to load winning rank data from JSON files
def load_rank(path, key, length=6):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
            # Sort numbers in each row and ensure correct length (6 for rank1/2, 5 for rank3)
            return [tuple(sorted(row[:length])) for row in data.get(key, [])]
    except Exception as e:
        print(f"{path} 파일 읽기 에러:", e) # Print error to console
        return []

# Load all historical winning numbers into sets for quick lookup
rank1 = load_rank(WINNING1_PATH, 'rank1', 6)
rank2 = load_rank(WINNING2_PATH, 'rank2', 6)
rank3 = load_rank(WINNING3_PATH, 'rank3', 5) # Rank 3 has 5 numbers + no bonus
ALL_WINNING = {
    "1": set(rank1),
    "2": set(rank2),
    "3": set(rank3) # Store rank3 as 5-number tuples
}

# Function to get frequently appearing numbers from recent N draws
def get_hot_numbers(n=5):
    all_nums = []
    # Extend all_nums with numbers from the last 'n' draws
    for row in rank1[-n:]:
        all_nums.extend(row)
    
    # Calculate frequency of each number
    freq = {}
    for num in all_nums:
        freq[num] = freq.get(num, 0) + 1
    
    # Sort numbers by frequency in descending order
    sorted_nums = [k for k, v in sorted(freq.items(), key=lambda x: -x[1])]
    return set(sorted_nums)

# Function to check if a set of numbers contains a consecutive sequence
def has_consecutive(numbers, seq_len=2):
    nums = sorted(list(numbers)) # Ensure sorted list for checking consecutiveness
    count = 1
    for i in range(1, len(nums)):
        if nums[i] == nums[i-1] + 1:
            count += 1
            if count >= seq_len: # If consecutive sequence reaches desired length
                return True
        else:
            count = 1 # Reset count if sequence breaks
    return False

# Function to generate lottery numbers based on various filters
def generate_numbers(
    exclude_ranks=[],
    exclude_hot_n=None,
    exclude_consecutive=None,
    user_exclude=None,
    user_include=None,
    count=1
):
    results = []
    tries = 0
    
    # Build a set of numbers to exclude based on winning ranks
    exclude_db = set()
    for r in exclude_ranks:
        exclude_db.update(ALL_WINNING.get(r, set()))
    
    # Get hot numbers to exclude if specified
    hot_numbers = get_hot_numbers(exclude_hot_n) if exclude_hot_n else set()
    
    # Generate numbers until the desired count is reached or max tries exceeded
    while len(results) < count:
        nums = set(random.sample(range(1, 46), 6)) # Generate 6 random numbers
        
        # Apply filters:
        # 1. User required numbers (user_include)
        if user_include and not set(user_include).issubset(nums):
            tries += 1
            if tries > 30000: break
            continue
        
        # 2. User excluded numbers (user_exclude)
        if user_exclude and nums.intersection(set(user_exclude)):
            tries += 1
            if tries > 30000: break
            continue
        
        # 3. Exclude past winning combinations (by rank)
        # For rank 3, check only 5 numbers of the generated set
        if exclude_db:
            if tuple(sorted(nums)) in ALL_WINNING.get("1", set()): # Check against rank 1
                tries += 1
                if tries > 30000: break
                continue
            if tuple(sorted(nums)) in ALL_WINNING.get("2", set()): # Check against rank 2
                tries += 1
                if tries > 30000: break
                continue
            # For rank 3, check all 6C5 combinations of the generated numbers
            is_rank3_match = False
            for combo in itertools.combinations(nums, 5):
                if tuple(sorted(combo)) in ALL_WINNING.get("3", set()):
                    is_rank3_match = True
                    break
            if is_rank3_match:
                tries += 1
                if tries > 30000: break
                continue

        # 4. Exclude recent hot numbers
        if exclude_hot_n and nums.intersection(hot_numbers):
            tries += 1
            if tries > 30000: break
            continue
        
        # 5. Exclude consecutive numbers if specified
        if exclude_consecutive and has_consecutive(nums, exclude_consecutive):
            tries += 1
            if tries > 30000: break
            continue
        
        # 6. Prevent duplicate sets in the results
        if sorted(list(nums)) in results: # Convert set to list, sort, then check
            tries += 1
            if tries > 30000: break
            continue
            
        results.append(sorted(list(nums))) # Add sorted list of numbers to results
        tries += 1 # Increment tries for valid numbers found

        if tries > 30000: # Safety break to prevent infinite loops
            break
    return results

# Function to parse a comma-separated string of integers into a list
def parse_int_list(text):
    if not text:
        return []
    return [int(n) for n in str(text).replace(" ", "").split(",") if str(n).isdigit()]

# Route for the free recommendation page (root URL)
@app.route("/", methods=["GET", "POST"])
def free():
    log_event("visit", {"page": "index"}) # Log page visit
    numbers = None
    error = ""
    
    # Initialize recommendation counters
    total_recs = 0
    today_recs = 0
    
    # Read admin log to count recommendations
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    try:
        with open("admin_log.json", encoding="utf-8") as f:
            for line in f:
                if '"event": "recommend"' in line: # Check for 'recommend' event
                    total_recs += 1
                    if today in line: # Check if event occurred today
                        today_recs += 1
    except:
        pass # Ignore if log file doesn't exist or is unreadable
        
    if request.method == "POST":
        numbers = generate_numbers(count=1) # Generate 1 set of numbers
        log_event("recommend", { # Log the recommendation event
            "page": "index",
            "numbers": numbers,
            "user_ip": request.remote_addr # Log user's IP address
        })
        if not numbers:
            error = "추천 가능한 번호가 없습니다." # Set error if no numbers generated
            
    return render_template(
        "index.html",
        numbers=numbers,
        error=error,
        total_recs=total_recs,
        today_recs=today_recs
    )

# Route for the filtered recommendation page
@app.route("/filter", methods=["GET", "POST"])
def filter_page():
    log_event("visit", {"page": "filter"}) # Log page visit
    numbers = []
    form = {}
    error = ""
    
    if request.method == "POST":
        try:
            hot_pick_n = int(request.form.get("hot_pick_n") or 0) or None
            count = int(request.form.get("count") or 1)
            
            # If hot_pick_n is selected, process hot numbers
            if hot_pick_n:
                # 1) Get recent N rounds' numbers
                recent_nums = []
                for row in rank1[-hot_pick_n:]:
                    recent_nums.extend(row)
                
                # 2) Count frequency of numbers
                counts = Counter(recent_nums)
                
                # 3) Select top 6 most common numbers
                generated_numbers = []
                for _ in range(count):
                    top6 = [num for num, cnt in counts.most_common(6)]
                    if len(top6) < 6:
                        # Fill remaining slots with random numbers if less than 6 hot numbers
                        top6 += random.sample([n for n in range(1,46) if n not in top6], 6 - len(top6))
                    random.shuffle(top6) # Shuffle the numbers
                    generated_numbers.append(sorted(top6)) # Add sorted numbers to list
                
                numbers = generated_numbers # Assign generated numbers to 'numbers'
                form = dict(request.form) # Store form data
                
                log_event("recommend", { # Log the recommendation event
                    "page": "filter-hot",
                    "numbers": numbers,
                    "user_ip": request.remote_addr,
                    "condition": dict(request.form)
                })
                # Return early if hot_pick_n was handled
                return render_template("filter.html", numbers=numbers, error=error, form=form)
            
            # If hot_pick_n is NOT selected, proceed with other filters
            else:
                exclude_ranks = request.form.getlist("exclude_ranks")
                exclude_hot_n = int(request.form.get("exclude_hot_n") or 0) or None
                exclude_consecutive = int(request.form.get("exclude_consecutive") or 0) or None
                user_exclude = parse_int_list(request.form.get("user_exclude", ""))
                user_include = parse_int_list(request.form.get("user_include", ""))
                count = int(request.form.get("count") or 5) # Default count for general filters
                
                # Error handling for user_include (only 1 number allowed as fixed)
                if len(user_include) > 1:
                    error = "고정할 번호는 1개만 입력할 수 있습니다."
                    numbers = [] # Clear numbers in case of error
                else:
                    # Generate numbers with all specified filters
                    numbers = generate_numbers(
                        exclude_ranks=exclude_ranks,
                        exclude_hot_n=exclude_hot_n,
                        exclude_consecutive=exclude_consecutive,
                        user_exclude=user_exclude,
                        user_include=user_include,
                        count=count
                    )
                    form = dict(request.form) # Store form data
                    
                    if not numbers and not error:
                        error = "조건에 맞는 추천번호가 없습니다. (필터를 줄여 다시 시도해주세요)"
        
        except Exception as e:
            error = f"입력값 오류: {e}" # Catch any input-related errors
            
    return render_template("filter.html", numbers=numbers, error=error, form=form)

# Route for the About page
@app.route('/about')
def about():
    log_event("visit", {"page": "about"})
    return render_template('about.html')

# Route for the Privacy Policy page
@app.route('/privacy')
def privacy():
    log_event("visit", {"page": "privacy"})
    return render_template('privacy.html')

# Route for the Disclaimer page
@app.route('/disclaimer')
def disclaimer():
    log_event("visit", {"page": "disclaimer"})
    return render_template('disclaimer.html')

# Route for the Contact page
@app.route('/contact')
def contact():
    log_event("visit", {"page": "contact"})
    return render_template('contact.html')

# Route for the Statistics page
@app.route('/stats')
def stats():
    log_event("visit", {"page": "stats"})
    recent_n = 10 # Default to recent 10 weeks (can be changed)
    numbers = []
    # Collect numbers from recent 'n' draws
    for row in rank1[-recent_n:]:
        numbers.extend(row)
    
    # Calculate frequency of all numbers (1-45)
    freq = dict(Counter(numbers))
    for n in range(1, 46):
        freq.setdefault(n, 0) # Ensure all numbers from 1 to 45 are in the frequency dictionary
    freq = dict(sorted(freq.items())) # Sort by number
    
    return render_template('stats.html', freq_json=freq, recent_n=recent_n)

# Route for the Admin page (requires password for access)
@app.route('/admin')
def admin():
    pw = request.args.get("pw", "")
    if pw != "1234": # Basic password check (should be more secure in production)
        return "관리자 인증 필요(pw=1234)", 403 # Unauthorized access
    
    logs = []
    try:
        # Load all logs from admin_log.json
        with open("admin_log.json", encoding="utf-8") as f:
            logs = [json.loads(line) for line in f if line.strip()]
    except:
        pass # Ignore if log file doesn't exist
    
    # Aggregate statistics from logs
    total_visits = sum(1 for log in logs if log["event"]=="visit")
    total_recs = sum(1 for log in logs if log["event"]=="recommend")
    
    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs)

# Route to update winning numbers (admin functionality)
@app.route("/update_winning", methods=["POST"])
def update_winning():
    pw = request.form.get("pw")
    
    # Password authentication
    if pw != "1234": # Basic password check
        # If authentication fails, render admin page with an error message
        logs = []
        try:
            with open("admin_log.json", encoding="utf-8") as f:
                logs = [json.loads(line) for line in f if line.strip()]
        except:
            pass
        total_visits = sum(1 for log in logs if log["event"] == "visit")
        total_recs = sum(1 for log in logs if log["event"] == "recommend")
        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, msg="비밀번호가 틀렸습니다.")

    # Fetch latest winning numbers
    latest, nums = fetch_latest_lotto_number()
    
    # If numbers are not yet available for the latest round
    if latest is None or nums is None:
        msg = "아직 최신 회차 당첨번호가 공개되지 않았습니다.<br>잠시 후 다시 시도해 주세요."
        # Render admin page with status message
        logs = []
        try:
            with open("admin_log.json", encoding="utf-8") as f:
                logs = [json.loads(line) for line in f if line.strip()]
        except:
            pass
        total_visits = sum(1 for log in logs if log["event"] == "visit")
        total_recs = sum(1 for log in logs if log["event"] == "recommend")
        return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, msg=msg)
        
    # Load existing rank 1 data
    try:
        with open(WINNING1_PATH, encoding="utf-8") as f:
            db = json.load(f)
    except:
        db = {"rank1": []} # Initialize if file doesn't exist
        
    # Add new winning numbers if not already present
    if nums not in db["rank1"]:
        db["rank1"].append(nums)
        with open(WINNING1_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2) # Save with pretty print
        msg = f"{latest}회차 번호 {nums} 저장 완료!"
    else:
        msg = "이미 최신 번호가 반영되어 있습니다."

    # Re-render admin dashboard with the update message
    logs = []
    try:
        with open("admin_log.json", encoding="utf-8") as f:
            logs = [json.loads(line) for line in f if line.strip()]
    except:
        pass
    total_visits = sum(1 for log in logs if log["event"] == "visit")
    total_recs = sum(1 for log in logs if log["event"] == "recommend")
    return render_template("admin.html", logs=logs, total_visits=total_visits, total_recs=total_recs, msg=msg)

# Route for ads.txt (for ad services)
@app.route('/ads.txt')
def ads_txt():
    return app.send_static_file('ads.txt')

# Health check endpoint for deployment environments
@app.route("/healthz", methods=["GET", "HEAD"])
def healthz():
    return "OK", 200

# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True)


import os
import sys
import time
import json
import shlex
import subprocess
import threading
from datetime import datetime
import telebot
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
USER_ID = os.getenv("TELEGRAM_USER_ID")

if not BOT_TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN is not set in .env")
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# Global state for session management
current_session_id = f"sess_{int(time.time())}"
DATA_DIR = os.path.abspath("data")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)

def get_opencode_cmd(prompt):
    """Determine the correct command to run OpenCode depending on the OS."""
    binary_path = "/home/suryansh/.opencode/bin/opencode"
    if sys.platform == "win32":
        return ["wsl", binary_path, "run", prompt]
    return [binary_path, "run", prompt]

def create_codebase_snapshot():
    """Generate a visual representation of the codebase using Pillow."""
    try:
        # Configuration for the image
        img_width = 800
        img_height = 600
        bg_color = (24, 24, 27)  # Dark theme zinc-900
        text_color = (228, 228, 231)  # zinc-200
        accent_color = (56, 189, 248)  # sky-400
        
        image = Image.new("RGB", (img_width, img_height), color=bg_color)
        draw = ImageDraw.Draw(image)
        
        # Try to load a nice font, fallback to default
        try:
            font_title = ImageFont.truetype("arial.ttf", 28)
            font_text = ImageFont.truetype("consola.ttf", 16)
        except IOError:
            font_title = ImageFont.load_default()
            font_text = ImageFont.load_default()

        # Draw Title
        title_text = "OpenCode Assistant - Codebase Snapshot"
        draw.text((30, 30), title_text, font=font_title, fill=accent_color)
        
        # Draw Session Details
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.text((30, 70), f"Timestamp: {timestamp}", font=font_text, fill=text_color)
        draw.text((30, 95), f"Active Session: {current_session_id}", font=font_text, fill=text_color)
        draw.text((30, 120), f"Isolated DB: data/sessions/{current_session_id}/opencode.db", font=font_text, fill=text_color)
        
        # Collect directory tree (simple version)
        draw.text((30, 170), "Repository Structure:", font=font_title, fill=accent_color)
        
        ignored_dirs = {".git", "node_modules", "venv", "env", "__pycache__", ".gemini"}
        tree_lines = []
        
        def build_tree(path, depth=0, max_depth=3):
            if depth > max_depth or len(tree_lines) > 15:
                return
            
            try:
                entries = sorted(os.listdir(path))
            except Exception:
                return
                
            dirs = [e for e in entries if os.path.isdir(os.path.join(path, e)) and e not in ignored_dirs]
            files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
            
            for d in dirs:
                tree_lines.append("  " * depth + f"📁 {d}/")
                build_tree(os.path.join(path, d), depth + 1, max_depth)
            for f in files[:5]: # Show max 5 files per directory to save space
                tree_lines.append("  " * depth + f"📄 {f}")
            if len(files) > 5:
                tree_lines.append("  " * depth + f"   ... and {len(files) - 5} more files")

        build_tree(".")
        
        # Draw the tree
        y_offset = 220
        for line in tree_lines:
            draw.text((30, y_offset), line, font=font_text, fill=text_color)
            y_offset += 22
            if y_offset > img_height - 40:
                draw.text((30, y_offset), "... (truncated)", font=font_text, fill=text_color)
                break
                
        snapshot_path = os.path.join(SESSIONS_DIR, current_session_id, "snapshot.png")
        os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
        image.save(snapshot_path)
        return snapshot_path
    except Exception as e:
        print(f"Failed to create snapshot: {e}")
        return None

def sync_git():
    """Automate git commit and push."""
    try:
        # Check if git is initialized
        if not os.path.exists(".git"):
            print("Git repository not initialized. Initializing...")
            subprocess.run(["git", "init"], check=True)
            # Add remote if provided
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/Surya854/Inspect.git"], check=False)
            
        subprocess.run(["git", "add", "."], check=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_msg = f"Auto-save: Codebase snapshot - {timestamp}"
        
        # Commit (will fail if nothing to commit, which is fine)
        result = subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True, text=True)
        if result.returncode == 0:
            print("Changes committed successfully.")
            # Push changes
            subprocess.run(["git", "push", "origin", "main"], check=False)
        else:
            print("No changes to commit.")
    except Exception as e:
        print(f"Git sync failed: {e}")

def background_task():
    """Runs every 30 minutes to sync git, take snapshot, and rotate session."""
    global current_session_id
    while True:
        # Wait 30 minutes
        time.sleep(30 * 60)
        print("Running 30-minute automated tasks...")
        
        # 1. Sync Git
        sync_git()
        
        # 2. Take Snapshot (of the current session state)
        snapshot_path = create_codebase_snapshot()
        
        # 3. Send update to Telegram
        if USER_ID:
            try:
                caption = f"🔄 **Automated 30-Min Sync**\n\nGit changes committed and pushed.\nEnding session: `{current_session_id}`"
                if snapshot_path and os.path.exists(snapshot_path):
                    with open(snapshot_path, "rb") as photo:
                        bot.send_photo(USER_ID, photo, caption=caption, parse_mode="Markdown")
                else:
                    bot.send_message(USER_ID, caption, parse_mode="Markdown")
            except Exception as e:
                print(f"Failed to send telegram update: {e}")
        
        # 4. Start new session
        current_session_id = f"sess_{int(time.time())}"
        print(f"Started new session: {current_session_id}")
        
        if USER_ID:
            try:
                bot.send_message(USER_ID, f"✨ **New Session Started:** `{current_session_id}`\nIsolated SQLite database initialized.", parse_mode="Markdown")
            except:
                pass

def is_authorized(message):
    """Check if the user is authorized to use the bot."""
    if not USER_ID:
        return True # Allow all if no USER_ID specified
    return str(message.from_user.id) == str(USER_ID)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not is_authorized(message):
        return
    bot.reply_to(message, "👋 Welcome to the OpenCode Assistant Wrapper!\n\nSend me any coding task or query, and I'll execute it using OpenCode.\n\nCommands:\n`/recover` - Force hallucination recovery mode\n`/new_session` - Manually start a new isolated session")

@bot.message_handler(commands=['new_session'])
def manual_new_session(message):
    if not is_authorized(message):
        return
    global current_session_id
    current_session_id = f"sess_{int(time.time())}"
    bot.reply_to(message, f"✨ **Manual Override:** New Session Started: `{current_session_id}`\nIsolated SQLite database initialized.", parse_mode="Markdown")

@bot.message_handler(commands=['recover'])
def force_recover(message):
    if not is_authorized(message):
        return
    bot.reply_to(message, "Initiating hallucination recovery... Send your next query, and I will strictly review the source code before answering.")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    if not is_authorized(message):
        bot.reply_to(message, "Unauthorized user.")
        return

    prompt = message.text
    
    # Check for hallucination keywords
    hallucination_triggers = ["hallucinat", "/recover", "confused", "wrong", "read your code"]
    is_recovering = any(trigger in prompt.lower() for trigger in hallucination_triggers)
    
    if is_recovering:
        prompt = (
            f"{prompt}\n\n"
            "[SYSTEM ALERT: The user suspects you are hallucinating or confused. "
            "You MUST use your file tools (ls, view, grep) to inspect your own source code "
            "located in the './opencode' directory to regain a correct understanding of your internal functionality before responding.]"
        )
    
    # Notify user that we are processing
    processing_msg = bot.reply_to(message, "⏳ Processing with OpenCode...")
    
    # Configure environment for OpenCode to isolate the SQLite database
    session_data_dir = os.path.join(SESSIONS_DIR, current_session_id)
    os.makedirs(session_data_dir, exist_ok=True)
    
    # In Viper, data.directory maps to OPENCODE_DATA_DIRECTORY automatically 
    # but due to nested structures, sometimes it maps to OPENCODE_DATA_DIRECTORY
    # We will set OPENCODE_DATA_DIRECTORY.
    env = os.environ.copy()
    
    # Convert path to WSL format if running on Windows and using WSL command
    wsl_data_dir = session_data_dir
    if sys.platform == "win32":
        # Convert C:\path\to\data to /mnt/c/path/to/data for WSL
        drive, tail = os.path.splitdrive(session_data_dir)
        if drive:
            drive_letter = drive[0].lower()
            wsl_data_dir = f"/mnt/{drive_letter}{tail.replace(chr(92), '/')}"
    
    env["OPENCODE_DATA_DIRECTORY"] = wsl_data_dir
    
    cmd = get_opencode_cmd(prompt)
    
    try:
        # Run OpenCode as a subprocess
        print(f"Running command: {' '.join(cmd)}")
        print(f"Session data dir: {wsl_data_dir}")
        
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            error_msg = f"❌ OpenCode encountered an error (Code {process.returncode}):\n```\n{stderr.strip()[:1000]}\n```"
            bot.edit_message_text(error_msg, chat_id=message.chat.id, message_id=processing_msg.message_id, parse_mode="Markdown")
            return
            
        # Success! Send the output back to Telegram
        output = stdout.strip()
        if not output:
            output = "✅ Task completed (No output returned)."
            
        # Telegram has a 4096 character limit per message
        max_len = 4000
        if len(output) > max_len:
            # Send in chunks or as a document
            with open("response.txt", "w", encoding="utf-8") as f:
                f.write(output)
            with open("response.txt", "rb") as doc:
                bot.send_document(message.chat.id, doc, caption="Output was too long, attached as file.")
            bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        else:
            bot.edit_message_text(output, chat_id=message.chat.id, message_id=processing_msg.message_id)
            
    except Exception as e:
        bot.edit_message_text(f"❌ Failed to execute OpenCode: {str(e)}", chat_id=message.chat.id, message_id=processing_msg.message_id)

if __name__ == "__main__":
    print(f"Starting OpenCode Wrapper Coordinator...")
    print(f"Initial Session ID: {current_session_id}")
    
    # Start the background task
    bg_thread = threading.Thread(target=background_task, daemon=True)
    bg_thread.start()
    
    # Start polling Telegram
    print("Listening for Telegram messages...")
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        print("Shutting down...")

from dotenv import load_dotenv
load_dotenv()
import asyncio
import edge_tts
from playsound import playsound
import uuid
import os
import datetime
import speech_recognition as sr
import webbrowser as wb
import pyautogui
import pyjokes
import requests
import json
import re
import subprocess
import time
import threading

# ================== MEMORY SYSTEM ==================

# File to store conversation memory
MEMORY_FILE = "jarvis_memory.json"

def load_memory():
    """Load memory from file"""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                memory = json.load(f)
                print(f"💾 Loaded {len(memory.get('conversations', []))} past conversations")
                return memory
        except Exception as e:
            print(f"❌ Error loading memory: {e}")
            return {"conversations": [], "facts": {}, "preferences": {}}
    return {"conversations": [], "facts": {}, "preferences": {}}

def save_memory(memory):
    """Save memory to file"""
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(memory, f, indent=2, ensure_ascii=False)
        print("💾 Memory saved")
    except Exception as e:
        print(f"❌ Error saving memory: {e}")

def add_to_conversation_history(memory, user_input, assistant_response):
    """Add conversation to history"""
    conversation = {
        "timestamp": datetime.datetime.now().isoformat(),
        "user": user_input,
        "assistant": assistant_response
    }
    memory["conversations"].append(conversation)
    
    # Keep only last 50 conversations to avoid file getting too large
    if len(memory["conversations"]) > 50:
        memory["conversations"] = memory["conversations"][-50:]
    
    return memory

def get_recent_context(memory, num_messages=5):
    """Get recent conversation context for LLM"""
    conversations = memory.get("conversations", [])
    recent = conversations[-num_messages:] if len(conversations) > num_messages else conversations
    
    context = ""
    for conv in recent:
        context += f"User: {conv['user']}\nAssistant: {conv['assistant']}\n\n"
    
    return context

def save_fact(memory, key, value):
    """Save a fact about the user"""
    memory["facts"][key] = {
        "value": value,
        "timestamp": datetime.datetime.now().isoformat()
    }
    save_memory(memory)
    print(f"📝 Saved fact: {key} = {value}")

def get_fact(memory, key):
    """Retrieve a saved fact"""
    return memory["facts"].get(key, {}).get("value")

def save_preference(memory, key, value):
    """Save a user preference"""
    memory["preferences"][key] = {
        "value": value,
        "timestamp": datetime.datetime.now().isoformat()
    }
    save_memory(memory)
    print(f"⚙️ Saved preference: {key} = {value}")

def get_preference(memory, key):
    """Retrieve a saved preference"""
    return memory["preferences"].get(key, {}).get("value")

def search_memory(memory, keyword):
    """Search through conversation history"""
    keyword = keyword.lower()
    results = []
    
    for conv in memory.get("conversations", []):
        if keyword in conv["user"].lower() or keyword in conv["assistant"].lower():
            results.append(conv)
    
    return results

# ================== OPENROUTER CONFIG ==================

OPENROUTER_API_KEY = "API"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "deepseek/deepseek-r1-0528:free"

# ================== TEXT CLEANUP ==================

def extract_urls(text):
    """Extract all URLs from text"""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    return urls

def clean_text_for_speech(text):
    """Remove markdown, code blocks, and special characters from LLM output"""
    # Remove code blocks
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]*`', '', text)
    
    # Remove markdown headers
    text = re.sub(r'#{1,6}\s+', '', text)
    
    # Remove markdown bold/italic
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    
    # Remove markdown links [text](url) but keep the URL for extraction
    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'\1 \2', text)
    
    # Remove special symbols commonly used in markdown
    text = text.replace('•', '')
    text = text.replace('→', 'to')
    text = text.replace('✓', 'check')
    text = text.replace('✗', 'cross')
    text = text.replace('—', '-')
    text = text.replace('–', '-')
    
    # Remove bullet points and numbered lists
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    
    # Remove extra whitespace and newlines
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    
    # Remove URLs from speech text (they'll be handled separately)
    text = re.sub(r'https?://[^\s<>"{}|\\^`\[\]]+', '', text)
    
    # Remove any remaining special characters that might cause issues
    text = re.sub(r'[^\w\s.,!?-]', '', text)
    
    return text.strip()

def ask_to_open_links(urls):
    """Ask user if they want to open the links provided by AI"""
    if not urls:
        return
    
    if len(urls) == 1:
        print(f"\n🔗 Link found: {urls[0]}")
        speak(f"I found a link. Would you like me to open it?")
    else:
        print(f"\n🔗 {len(urls)} links found:")
        for i, url in enumerate(urls, 1):
            print(f"   {i}. {url}")
        speak(f"I found {len(urls)} links. Would you like me to open them?")
    
    response = takecommand()
    if response:
        resp = response.lower()
        if any(word in resp for word in ["yes", "yeah", "sure", "open", "okay", "ok", "yep"]):
            for url in urls:
                print(f"🌐 Opening: {url}")
                wb.open(url)
            speak(f"Opening {'the link' if len(urls) == 1 else 'all links'}")
        else:
            speak("Okay, not opening the links")
    else:
        speak("I didn't catch that, skipping the links")

# ================== VOICE (EDGE TTS) ==================

# Global flag to control speech interruption
stop_speaking = False

def speak(text):
    global stop_speaking
    stop_speaking = False
    
    # Clean the text before speaking
    clean_text = clean_text_for_speech(text)
    print(f"\n🗣️ Jarvis speaking:\n{clean_text}\n")

    async def _speak():
        global stop_speaking
        filename = f"voice_{uuid.uuid4()}.mp3"
        communicate = edge_tts.Communicate(
            text=clean_text,
            voice="en-IN-NeerjaNeural"
        )
        await communicate.save(filename)
        
        if not stop_speaking:
            try:
                # Start a thread to listen for "stop" command while speaking
                listener_thread = threading.Thread(target=listen_for_stop, daemon=True)
                listener_thread.start()
                
                playsound(filename)
            except Exception as e:
                if not stop_speaking:
                    print(f"Error playing sound: {e}")
            finally:
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except:
                        pass

    asyncio.run(_speak())

def listen_for_stop():
    """Background listener to detect 'stop' command while speaking"""
    global stop_speaking
    r = sr.Recognizer()
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = r.listen(source, timeout=1, phrase_time_limit=2)
            command = r.recognize_google(audio, language="en-in").lower()
            if "stop" in command or "quiet" in command or "silence" in command:
                stop_speaking = True
                print("🛑 Speech interrupted by user")
        except:
            pass

# ================== SPEECH INPUT ==================

def takecommand():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n🎤 Listening...")
        print("📢 Speak now! (Microphone is active)")
        
        # Increase energy threshold and adjust for ambient noise
        r.energy_threshold = 4000  # Increase if too sensitive
        r.dynamic_energy_threshold = True
        r.pause_threshold = 1.0  # How long to wait for pause
        
        try:
            # Adjust for ambient noise first
            print("🔧 Adjusting for ambient noise...")
            r.adjust_for_ambient_noise(source, duration=1)
            
            # Listen for audio
            print("✅ Ready! Speak your command...")
            audio = r.listen(source, timeout=10, phrase_time_limit=10)
            
            print("🧠 Recognizing your speech...")
            query = r.recognize_google(audio, language="en-in")
            print(f"✅ You said: '{query}'")
            return query
            
        except sr.WaitTimeoutError:
            print("⏱️ No speech detected. Timeout.")
            return None
        except sr.UnknownValueError:
            print("❌ Could not understand audio. Please speak clearly.")
            return None
        except sr.RequestError as e:
            print(f"❌ Recognition service error: {e}")
            return None
        except Exception as e:
            print(f"❌ Error: {e}")
            return None

# ================== OPENROUTER LLM ==================

def ask_llm(prompt, memory=None):
    print("\n📡 Sending to DeepSeek LLM...")

    if not OPENROUTER_API_KEY:
        print("❌ Missing OpenRouter API key")
        return "API key is missing. Please set OPENROUTER_API_KEY in your environment."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    # Build system message with memory context
    system_message = "You are Jarvis, a helpful AI voice assistant. Always reply in plain text without any markdown, code blocks, or special formatting. Keep responses brief, conversational, and under 3 sentences when possible."
    
    if memory:
        # Add facts and preferences to context
        if memory.get("facts"):
            facts_str = "\n".join([f"- {k}: {v['value']}" for k, v in memory["facts"].items()])
            system_message += f"\n\nKnown facts about the user:\n{facts_str}"
        
        if memory.get("preferences"):
            prefs_str = "\n".join([f"- {k}: {v['value']}" for k, v in memory["preferences"].items()])
            system_message += f"\n\nUser preferences:\n{prefs_str}"
        
        # Add recent conversation context
        recent_context = get_recent_context(memory, num_messages=3)
        if recent_context:
            system_message += f"\n\nRecent conversation history:\n{recent_context}"

    data = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = requests.post(OPENROUTER_URL, headers=headers, data=json.dumps(data), timeout=30)
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        print(f"\n🤖 LLM Reply (raw):\n{reply}\n")
        return reply
    except Exception as e:
        print("❌ LLM ERROR:", e)
        if hasattr(e, 'response') and e.response is not None:
            print("🔍 Response content:", e.response.text)
        return "Sorry, I am having trouble connecting to my brain."

# ================== SYSTEM FUNCTIONS ==================

def open_application(app_name):
    """Open various applications on Windows"""
    app_name = app_name.lower()
    
    apps = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "paint": "mspaint.exe",
        "chrome": "chrome.exe",
        "edge": "msedge.exe",
        "firefox": "firefox.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
        "task manager": "taskmgr.exe",
        "control panel": "control.exe",
        "settings": "ms-settings:",
        "word": "winword.exe",
        "excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
    }
    
    if app_name in apps:
        try:
            if app_name == "settings":
                os.system(f"start {apps[app_name]}")
            else:
                subprocess.Popen(apps[app_name])
            speak(f"Opening {app_name}")
            return True
        except Exception as e:
            print(f"❌ Error opening {app_name}: {e}")
            speak(f"Sorry, I couldn't open {app_name}")
            return False
    else:
        speak(f"I don't know how to open {app_name}")
        return False

def type_text(text):
    """Type text using virtual keyboard"""
    speak(f"Typing: {text}")
    time.sleep(0.5)  # Small delay before typing
    pyautogui.write(text, interval=0.05)
    print(f"⌨️ Typed: {text}")

def press_key(key_name):
    """Press specific keyboard keys"""
    key_name = key_name.lower().strip()
    
    key_mappings = {
        "enter": "enter",
        "return": "enter",
        "space": "space",
        "spacebar": "space",
        "backspace": "backspace",
        "delete": "delete",
        "tab": "tab",
        "escape": "esc",
        "esc": "esc",
        "shift": "shift",
        "control": "ctrl",
        "ctrl": "ctrl",
        "alt": "alt",
        "windows": "win",
        "win": "win",
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
        "page up": "pageup",
        "page down": "pagedown",
        "home": "home",
        "end": "end",
    }
    
    if key_name in key_mappings:
        pyautogui.press(key_mappings[key_name])
        speak(f"Pressed {key_name}")
        print(f"⌨️ Pressed: {key_name}")
    else:
        speak(f"I don't recognize the key {key_name}")

def keyboard_shortcut(keys):
    """Execute keyboard shortcuts like ctrl+c, alt+tab"""
    keys_list = [k.strip().lower() for k in keys.split("+")]
    
    key_mappings = {
        "control": "ctrl",
        "ctrl": "ctrl",
        "shift": "shift",
        "alt": "alt",
        "windows": "win",
        "win": "win",
    }
    
    # Map keys
    mapped_keys = [key_mappings.get(k, k) for k in keys_list]
    
    try:
        pyautogui.hotkey(*mapped_keys)
        speak(f"Executed shortcut {keys}")
        print(f"⌨️ Shortcut: {' + '.join(mapped_keys)}")
    except Exception as e:
        print(f"❌ Error with shortcut: {e}")
        speak("Sorry, I couldn't execute that shortcut")

def mouse_control(action, x=None, y=None):
    """Control mouse movements and clicks"""
    action = action.lower()
    
    if action == "click":
        pyautogui.click()
        speak("Clicked")
    elif action == "double click":
        pyautogui.doubleClick()
        speak("Double clicked")
    elif action == "right click":
        pyautogui.rightClick()
        speak("Right clicked")
    elif action == "move" and x and y:
        pyautogui.moveTo(x, y, duration=0.5)
        speak(f"Moved mouse to {x}, {y}")
    elif action == "scroll up":
        pyautogui.scroll(200)
        speak("Scrolled up")
    elif action == "scroll down":
        pyautogui.scroll(-200)
        speak("Scrolled down")

def minimize_window():
    """Minimize current window"""
    pyautogui.hotkey('win', 'down')
    speak("Minimizing window")

def maximize_window():
    """Maximize current window"""
    pyautogui.hotkey('win', 'up')
    speak("Maximizing window")

def close_window():
    """Close current window"""
    pyautogui.hotkey('alt', 'f4')
    speak("Closing window")

def switch_window():
    """Switch between windows"""
    pyautogui.hotkey('alt', 'tab')
    speak("Switching window")

def shutdown_system():
    speak("Shutting down the system in ten seconds")
    os.system("shutdown /s /t 10")

def restart_system():
    speak("Restarting the system in ten seconds")
    os.system("shutdown /r /t 10")

def take_screenshot():
    path = os.path.join(os.path.expanduser("~"), "Pictures", "jarvis_screenshot.png")
    img = pyautogui.screenshot()
    img.save(path)
    speak("Screenshot taken and saved")
    print(f"📸 Screenshot saved at: {path}")

# ================== GREETING ==================

def wishme():
    hour = datetime.datetime.now().hour
    if hour < 12:
        speak("Good morning!")
    elif hour < 16:
        speak("Good afternoon!")
    else:
        speak("Good evening!")

    speak("I am Jarvis. You can talk to me freely. Say stop to interrupt me, or say exit to end our conversation. I can also control your PC, open applications, and type for you.")
    
    # Test microphone
    print("\n🔊 Testing microphone...")
    print("📢 Please say something to test if I can hear you...")
    test = takecommand()
    if test:
        speak("Great! I can hear you perfectly")
    else:
        speak("I'm having trouble hearing you. Please check your microphone settings.")

# ================== MAIN LOOP ==================
print("🔑 API Key Loaded:", bool(OPENROUTER_API_KEY))

if __name__ == "__main__":
    # Load memory at startup
    memory = load_memory()
    
    wishme()

    while True:
        query = takecommand()
        if not query:
            continue

        q = query.lower()

        # Enhanced exit commands
        if any(word in q for word in ["exit", "offline", "stop", "goodbye", "bye", "quit"]):
            speak("Going offline. Goodbye!")
            save_memory(memory)
            break

        # ========== MEMORY COMMANDS ==========
        
        elif "remember" in q or "save" in q and "fact" in q:
            # Example: "remember my name is John" or "save the fact that I like pizza"
            speak("What should I remember?")
            fact_input = takecommand()
            if fact_input:
                # Try to extract key-value pairs
                if "my name is" in fact_input.lower():
                    name = fact_input.lower().split("my name is")[1].strip()
                    save_fact(memory, "name", name)
                    speak(f"I'll remember your name is {name}")
                elif "i like" in fact_input.lower():
                    thing = fact_input.lower().split("i like")[1].strip()
                    save_fact(memory, "likes", thing)
                    speak(f"Noted that you like {thing}")
                elif "i am" in fact_input.lower():
                    info = fact_input.lower().split("i am")[1].strip()
                    save_fact(memory, "about_user", info)
                    speak(f"Got it, you are {info}")
                else:
                    # Save as general fact
                    save_fact(memory, "general_info", fact_input)
                    speak("I've saved that information")
        
        elif "what do you know about me" in q or "what do you remember" in q:
            facts = memory.get("facts", {})
            prefs = memory.get("preferences", {})
            
            if not facts and not prefs:
                speak("I don't have any saved information about you yet")
            else:
                info = "Here's what I know: "
                if facts:
                    for key, value in facts.items():
                        info += f"{key} is {value['value']}. "
                if prefs:
                    for key, value in prefs.items():
                        info += f"You prefer {value['value']} for {key}. "
                speak(info)
        
        elif "forget" in q or "clear memory" in q:
            speak("Are you sure you want me to forget everything?")
            confirm = takecommand()
            if confirm and any(word in confirm.lower() for word in ["yes", "yeah", "sure", "confirm"]):
                memory = {"conversations": [], "facts": {}, "preferences": {}}
                save_memory(memory)
                speak("Memory cleared. Starting fresh")
            else:
                speak("Okay, keeping my memory intact")
        
        elif "search memory" in q or "search history" in q:
            speak("What should I search for?")
            keyword = takecommand()
            if keyword:
                results = search_memory(memory, keyword)
                if results:
                    speak(f"I found {len(results)} conversations about {keyword}")
                    for result in results[:3]:  # Show top 3
                        print(f"\n📜 {result['timestamp']}")
                        print(f"You: {result['user']}")
                        print(f"Me: {result['assistant']}\n")
                else:
                    speak(f"I couldn't find anything about {keyword} in our history")

        # ========== PC CONTROL COMMANDS ==========
        
        # Open applications
        elif "open notepad" in q:
            open_application("notepad")
        
        elif "open calculator" in q:
            open_application("calculator")
        
        elif "open paint" in q:
            open_application("paint")
        
        elif "open chrome" in q or "open google chrome" in q:
            open_application("chrome")
        
        elif "open edge" in q:
            open_application("edge")
        
        elif "open file explorer" in q or "open explorer" in q:
            open_application("explorer")
        
        elif "open task manager" in q:
            open_application("task manager")
        
        elif "open settings" in q:
            open_application("settings")
        
        elif "open command prompt" in q or "open cmd" in q:
            open_application("cmd")
        
        # Typing commands
        elif "type" in q:
            # Extract text after "type"
            text_to_type = q.split("type", 1)[1].strip()
            if text_to_type:
                type_text(text_to_type)
            else:
                speak("What should I type?")
        
        # Keyboard shortcuts
        elif "press enter" in q:
            press_key("enter")
        
        elif "press space" in q or "press spacebar" in q:
            press_key("space")
        
        elif "press backspace" in q:
            press_key("backspace")
        
        elif "press tab" in q:
            press_key("tab")
        
        elif "press escape" in q or "press esc" in q:
            press_key("escape")
        
        # Common shortcuts
        elif "copy" in q and "ctrl" not in q:
            keyboard_shortcut("ctrl+c")
        
        elif "paste" in q and "ctrl" not in q:
            keyboard_shortcut("ctrl+v")
        
        elif "cut" in q and "ctrl" not in q:
            keyboard_shortcut("ctrl+x")
        
        elif "undo" in q:
            keyboard_shortcut("ctrl+z")
        
        elif "save" in q and "ctrl" not in q:
            keyboard_shortcut("ctrl+s")
        
        elif "select all" in q:
            keyboard_shortcut("ctrl+a")
        
        elif "new tab" in q:
            keyboard_shortcut("ctrl+t")
        
        elif "close tab" in q:
            keyboard_shortcut("ctrl+w")
        
        # Window management
        elif "minimize window" in q or "minimize" in q:
            minimize_window()
        
        elif "maximize window" in q or "maximize" in q:
            maximize_window()
        
        elif "close window" in q:
            close_window()
        
        elif "switch window" in q or "next window" in q:
            switch_window()
        
        # Mouse controls
        elif "click" in q and "double" not in q and "right" not in q:
            mouse_control("click")
        
        elif "double click" in q:
            mouse_control("double click")
        
        elif "right click" in q:
            mouse_control("right click")
        
        elif "scroll up" in q:
            mouse_control("scroll up")
        
        elif "scroll down" in q:
            mouse_control("scroll down")

        # ========== OTHER COMMANDS ==========

        elif "time" in q:
            now = datetime.datetime.now().strftime("%I:%M %p")
            speak(f"The current time is {now}")

        elif "date" in q:
            today = datetime.datetime.now().strftime("%d %B %Y")
            speak(f"Today's date is {today}")

        elif "open youtube" in q:
            wb.open("https://youtube.com")
            speak("Opening YouTube")

        elif "open google" in q:
            wb.open("https://google.com")
            speak("Opening Google")

        elif "joke" in q:
            joke = pyjokes.get_joke()
            print(f"\n😂 Joke:\n{joke}\n")
            speak(joke)

        elif "screenshot" in q or "take screenshot" in q:
            take_screenshot()

        elif "shutdown" in q:
            shutdown_system()
            break

        elif "restart" in q:
            restart_system()
            break

        else:
            reply = ask_llm(query, memory)
            
            # Save conversation to memory
            memory = add_to_conversation_history(memory, query, reply)
            save_memory(memory)
            
            # Extract and handle any URLs in the response
            urls = extract_urls(reply)
            
            # Speak the reply (URLs removed by clean_text_for_speech)
            speak(reply)
            
            # Ask if user wants to open any links found
            if urls:
                ask_to_open_links(urls)
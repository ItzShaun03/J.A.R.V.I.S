import pyttsx3

engine = pyttsx3.init('sapi5')
engine.say("If you can hear this, text to speech is working")
engine.runAndWait()
engine.stop()

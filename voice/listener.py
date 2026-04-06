# voice/listener.py — futur pipeline microphone → STT → TTS
#
# Ce module accueillera la reconnaissance vocale (mic input → transcription
# via Whisper ou SpeechRecognition) et le renvoi du texte transcrit vers
# FrenchTTSApp._on_speak().
#
# Dépendances envisagées : openai-whisper, pyaudio ou sounddevice (entrée),
# éventuellement faster-whisper pour les performances sur CPU.
#
# À implémenter ultérieurement — ce fichier est un placeholder.

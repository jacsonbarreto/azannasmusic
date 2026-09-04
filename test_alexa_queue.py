import json
import unittest
from fastapi.testclient import TestClient
from main import app, alexa_sessions

client = TestClient(app)

class TestAlexaWebhook(unittest.TestCase):

    def setUp(self):
        alexa_sessions.clear()
        self.device_id = "test_device_123"

    def test_01_play_music_intent(self):
        """Testa o comando inicial de busca e início de reprodução com rádio."""
        payload = {
            "version": "1.0",
            "context": {
                "System": {
                    "device": {"deviceId": self.device_id},
                    "user": {"userId": "test_user_456"}
                }
            },
            "request": {
                "type": "IntentRequest",
                "intent": {
                    "name": "PlayMusicIntent",
                    "slots": {
                        "query": {"name": "query", "value": "Legiao Urbana"}
                    }
                }
            }
        }
        res = client.post("/alexa", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # Verificar fala
        speech = data.get("response", {}).get("outputSpeech", {}).get("text", "")
        print(f"\n[TEST 1 - Speech]: {speech}")
        self.assertIn("Tocando", speech)
        self.assertIn("o player do jaquinho lindão e das annas", speech)

        # Verificar diretiva AudioPlayer.Play REPLACE_ALL
        directives = data.get("response", {}).get("directives", [])
        self.assertTrue(len(directives) > 0)
        self.assertEqual(directives[0]["type"], "AudioPlayer.Play")
        self.assertEqual(directives[0]["playBehavior"], "REPLACE_ALL")

        # Verificar se sessão foi criada em memória
        self.assertIn(self.device_id, alexa_sessions)
        session = alexa_sessions[self.device_id]
        self.assertTrue(len(session["queue"]) > 0)
        print(f"[TEST 1 - Fila Carregada]: {len(session['queue'])} faixas.")

    def test_02_playback_nearly_finished(self):
        """Testa o enfileiramento automático da próxima música (Autoplay)."""
        # Primeiro iniciar a sessão
        self.test_01_play_music_intent()

        payload = {
            "version": "1.0",
            "context": {
                "System": {
                    "device": {"deviceId": self.device_id}
                }
            },
            "request": {
                "type": "AudioPlayer.PlaybackNearlyFinished"
            }
        }
        res = client.post("/alexa", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        directives = data.get("response", {}).get("directives", [])
        self.assertTrue(len(directives) > 0)
        self.assertEqual(directives[0]["type"], "AudioPlayer.Play")
        self.assertEqual(directives[0]["playBehavior"], "ENQUEUE")
        print(f"[TEST 2 - Autoplay Enqueued]: Next stream token = {directives[0]['audioItem']['stream']['token']}")

    def test_03_what_is_playing_intent(self):
        """Testa a pergunta 'que música está tocando?'."""
        self.test_01_play_music_intent()

        payload = {
            "version": "1.0",
            "context": {
                "System": {
                    "device": {"deviceId": self.device_id}
                }
            },
            "request": {
                "type": "IntentRequest",
                "intent": {
                    "name": "WhatIsPlayingIntent"
                }
            }
        }
        res = client.post("/alexa", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        speech = data.get("response", {}).get("outputSpeech", {}).get("text", "")
        print(f"[TEST 3 - WhatIsPlaying Speech]: {speech}")
        self.assertIn("Você está ouvindo", speech)

    def test_04_pause_and_resume(self):
        """Testa os comandos de pausar e retomar mantendo o offset."""
        self.test_01_play_music_intent()

        # Simular PlaybackStopped com offset
        stop_event = {
            "version": "1.0",
            "context": {
                "System": {
                    "device": {"deviceId": self.device_id}
                }
            },
            "request": {
                "type": "AudioPlayer.PlaybackStopped",
                "offsetInMilliseconds": 45000
            }
        }
        client.post("/alexa", json=stop_event)

        # Enviar ResumeIntent
        resume_payload = {
            "version": "1.0",
            "context": {
                "System": {
                    "device": {"deviceId": self.device_id}
                }
            },
            "request": {
                "type": "IntentRequest",
                "intent": {
                    "name": "AMAZON.ResumeIntent"
                }
            }
        }
        res = client.post("/alexa", json=resume_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        directives = data.get("response", {}).get("directives", [])
        self.assertEqual(directives[0]["audioItem"]["stream"]["offsetInMilliseconds"], 45000)
        print(f"[TEST 4 - Resume Offset]: Retomou exatamente de {directives[0]['audioItem']['stream']['offsetInMilliseconds']} ms")

if __name__ == "__main__":
    unittest.main()



import os
import io
import asyncio
import discord
import numpy as np
import soundfile as sf


from math import gcd
from functools import lru_cache
from scipy.signal import resample_poly
from faster_whisper import WhisperModel
from dotenv import load_dotenv




# ==========================================
# 1. 디스코드 봇 기본 설정
# ==========================================


load_dotenv()


TOKEN = os.getenv("DISCORD_TOKEN")


bot = discord.Bot()


# VoiceClient만으로는 녹음 reader가 조기 종료된 세션을 구분하기 어렵습니다.
recording_sessions = {}




# ==========================================
# 2. AI 모델 불러오기
# ==========================================


@lru_cache(maxsize=1)
def load_model():


   print("Whisper AI 모델을 불러오는 중...")


   model = WhisperModel(
       "base",
       device="cpu",
       compute_type="int8"
   )


   print("Whisper AI 모델 로딩 완료!")


   return model




# ==========================================
# 3. 음성 데이터를 텍스트로 변환
# ==========================================


def transcribe_audio(wav_bytes):


   # WAV 바이트 데이터를 NumPy 배열로 읽기
   audio, sample_rate = sf.read(
       io.BytesIO(wav_bytes),
       dtype="float32"
   )


   # 스테레오 음성을 모노로 변환
   if audio.ndim == 2:
       audio = audio.mean(axis=1)


   # Whisper 입력에 맞게 16kHz로 변경
   if sample_rate != 16000:


       divisor = gcd(sample_rate, 16000)


       audio = resample_poly(
           audio,
           16000 // divisor,
           sample_rate // divisor
       )


   audio = np.asarray(audio, dtype=np.float32)


   # 1초 미만 음성은 분석하지 않음
   if len(audio) < 16000:
       return ""


   # AI 모델 불러오기
   model = load_model()


   print("AI 음성 분석 중...")


   # Whisper로 음성 인식
   segments, info = model.transcribe(
       audio,
       language="ko",
       beam_size=5,
       vad_filter=True
   )


   # 인식된 문장을 하나로 합치기
   text = " ".join(
       segment.text.strip()
       for segment in segments
   )


   return text.strip()




# ==========================================
# 4. 녹음 종료 후 음성 인식
# ==========================================


async def recording_finished(
   sink,
   text_channel,
   voice_client
):


   try:


       # 녹음된 음성이 없는 경우
       if not sink.audio_data:


           await text_channel.send(
               "녹음된 음성이 없습니다.\n"
               "디스코드 DAVE 음성 수신 호환성을 확인하세요."
           )


           return


       await text_channel.send(
           "녹음 완료! AI 음성 인식을 시작합니다."
       )


       # 사용자별 음성 데이터 처리
       for user_id, recorded_audio in sink.audio_data.items():


           try:


               print(f"사용자 {user_id} 음성 분석 시작")


               # 녹음 파일 읽기
               recorded_audio.file.seek(0)


               wav_bytes = recorded_audio.file.read()


               # AI 음성 인식은 별도 스레드에서 실행
               text = await asyncio.to_thread(
                   transcribe_audio,
                   wav_bytes
               )


               # 인식된 문장이 있다면
               if text:


                   print(f"인식 결과: {text}")


                   # 디스코드 메시지 길이 제한 고려
                   for i in range(0, len(text), 1700):


                       chunk = text[i:i + 1700]


                       await text_channel.send(
                           f"<@{user_id}>: {chunk}",
                           allowed_mentions=discord.AllowedMentions.none()
                       )


               else:


                   await text_channel.send(
                       f"<@{user_id}>: 인식된 음성이 없습니다.",
                       allowed_mentions=discord.AllowedMentions.none()
                   )


           except Exception as exc:


               print("사용자 음성 인식 오류:", repr(exc))


               await text_channel.send(
                   "일부 음성 인식에 실패했습니다.\n"
                   "PyCharm 실행창을 확인하세요."
               )


       await text_channel.send(
           "AI 자막 생성 완료!"
       )


   except Exception as exc:


       print("녹음 종료 처리 오류:", repr(exc))


   finally:


       recording_sessions.pop(voice_client.guild.id, None)


       # 녹음이 종료되면 음성 채널 연결 해제
       try:
           if voice_client.is_connected():
               await voice_client.disconnect()


       except Exception as exc:
           print("음성 연결 해제 오류:", repr(exc))




# ==========================================
# 5. 봇 로그인 완료 이벤트
# ==========================================


@bot.event
async def on_ready():


   print(f"{bot.user} 로그인 완료")


   print("디스코드 음성 인식 봇 준비 완료!")


   print(f"Pycord 버전: {discord.__version__}")




# ==========================================
# 6. /start 명령어
# ==========================================


@bot.slash_command(
   name="start2",
   description="음성 채널에 입장하고 녹음을 시작합니다."
)
async def start2(ctx: discord.ApplicationContext):


   # 디스코드 명령어 응답 만료 방지
   await ctx.defer()


   # 서버에서 실행했는지 검사
   if ctx.guild is None:


       await ctx.followup.send(
           "서버에서만 사용할 수 있습니다."
       )


       return


   # 사용자가 음성 채널에 있는지 검사
   if ctx.author.voice is None:


       await ctx.followup.send(
           "먼저 음성 채널에 입장하세요."
       )


       return


   # 이미 봇이 연결되어 있는지 검사
   if ctx.guild.voice_client is not None:


       await ctx.followup.send(
           "봇이 이미 음성 채널에 있습니다."
       )


       return


   voice_client = None
   recording_started = False


   try:


       # 1. 사용자의 음성 채널에 연결
       voice_client = await ctx.author.voice.channel.connect()


       print("음성 채널 연결 성공!")


       # 2. WAV 녹음 객체 생성
       sink = discord.sinks.WaveSink()


       # 3. Pycord Sink 인터페이스 호환성 검사
       if not isinstance(sink, discord.sinks.Sink) or not hasattr(sink, "__sink_listeners__"):


           print(
               "녹음 호환성 오류: "
               "WaveSink에 __sink_listeners__가 없습니다."
           )


           await ctx.followup.send(
               "음성 채널 연결은 성공했지만 "
               "Pycord 녹음 인터페이스가 호환되지 않습니다.\n"
               "Pycord 설치 버전과 DAVE 수신 지원을 확인하세요."
           )


           return


       # 4. 자막을 보낼 텍스트 채널
       text_channel = ctx.channel


       # 5. 녹음 종료 콜백
       # Pycord 2.8 개발 API의 AfterCallback은 error가 아니라 sink를 첫 인자로 받습니다.
       async def on_recording_stop(finished_sink):


           await recording_finished(
               finished_sink,
               text_channel,
               voice_client
           )


       # 6. 음성 녹음 시작
       voice_client.start_recording(
           sink,
           on_recording_stop
       )


       recording_sessions[ctx.guild.id] = {
           "voice_client": voice_client,
           "sink": sink,
           "text_channel": text_channel,
       }


       recording_started = True


       print("음성 녹음 시작!")


       await ctx.followup.send(
           "음성 녹음을 시작했습니다!\n"
           "녹음을 종료하려면 /stop을 입력하세요."
       )


   except Exception as exc:


       print("녹음 시작 오류:", repr(exc))


       await ctx.followup.send(
           "녹음 시작 중 오류가 발생했습니다.\n"
           f"오류 유형: {type(exc).__name__}\n"
           "자세한 내용은 PyCharm 실행창을 확인하세요."
       )


   finally:


       # 녹음이 시작되지 않았다면 연결 종료
       if not recording_started and voice_client is not None:


           try:


               if voice_client.is_connected():
                   await voice_client.disconnect()


           except Exception as exc:
               print("연결 종료 오류:", repr(exc))




# ==========================================
# 7. /stop 명령어
# ==========================================


@bot.slash_command(
   name="stop2",
   description="녹음을 종료하고 AI 자막을 생성합니다."
)
async def stop2(ctx: discord.ApplicationContext):


   # 명령어 응답 예약
   await ctx.defer()


   if ctx.guild is None:


       await ctx.followup.send(
           "서버에서만 사용할 수 있습니다."
       )


       return


   session = recording_sessions.get(ctx.guild.id)
   voice_client = ctx.guild.voice_client


   # 녹음 상태 확인
   if session is None or voice_client is None:


       await ctx.followup.send(
           "현재 녹음 중이 아닙니다."
       )


       return


   if session["voice_client"] is not voice_client:
       await ctx.followup.send("현재 음성 연결은 이 봇이 시작한 녹음 세션과 일치하지 않습니다.")
       return


   if not voice_client.is_recording():
       await ctx.followup.send(
           "녹음 reader가 이미 종료되어 /stop으로 마칠 수 없습니다.\n"
           "PyCharm 실행창에서 DAVE 수신 또는 Pycord 오류를 확인하세요."
       )
       return


   await ctx.followup.send(
       "녹음을 종료합니다.\n"
       "AI 음성 분석 결과는 녹음을 시작한 텍스트 채널에 출력됩니다."
   )


   # 녹음 종료
   try:


       voice_client.stop_recording()


       print("음성 녹음 종료")


   except Exception as exc:


       print("녹음 종료 오류:", repr(exc))




# ==========================================
# 8. 봇 실행
# ==========================================


if __name__ == "__main__":


   if not TOKEN:


       raise ValueError(
           ".env 파일에 DISCORD_TOKEN을 설정하세요."
       )


   bot.run(TOKEN)



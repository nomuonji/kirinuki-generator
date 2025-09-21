
import ffmpeg

input_video = ffmpeg.input('tmp/video.f616.mp4')
input_audio = ffmpeg.input('tmp/video.f234-1.mp4')

ffmpeg.concat(input_video, input_audio, v=1, a=1).output('tmp/video.mp4').run()

print("Files merged successfully!")

using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;

/// <summary>
/// Receives TTS reply audio from tools/miku_client.py's --headset path (CLAUDE.md step 7)
/// and plays it through an AudioSource — which on Quest comes out the headset speakers,
/// same as any other in-app sound, no extra routing needed.
///
/// TCP, not UDP: a sentence clip is a WAV file that can run well past UDP's 64 KB datagram
/// limit, and losing a chunk would garble speech. One accepted connection per chunk, each
/// framed as a 4-byte big-endian length + payload (miku_client._send_wav_to_headset).
/// </summary>
[RequireComponent(typeof(AudioSource))]
public class AudioPlaybackReceiver : MonoBehaviour
{
    [SerializeField] int port = 5008;

    AudioSource _source;
    TcpListener _listener;
    Thread _thread;
    volatile bool _running;

    readonly ConcurrentQueue<AudioClip> _pending = new ConcurrentQueue<AudioClip>();

    void Awake()
    {
        _source = GetComponent<AudioSource>();
        _source.playOnAwake = false;
    }

    void OnEnable()
    {
        _running = true;
        _listener = new TcpListener(System.Net.IPAddress.Any, port);
        _listener.Start();
        _thread = new Thread(AcceptLoop) { IsBackground = true };
        _thread.Start();
    }

    void OnDisable()
    {
        _running = false;
        _listener?.Stop();
        _thread?.Join(500);
    }

    void AcceptLoop()
    {
        while (_running)
        {
            try
            {
                using var client = _listener.AcceptTcpClient();
                using var stream = client.GetStream();
                var wavBytes = ReadFramedChunk(stream);
                var clip = WavUtility.ToAudioClip(wavBytes);
                if (clip != null) _pending.Enqueue(clip);
            }
            catch (SocketException)
            {
                // Listener.Stop() unblocks AcceptTcpClient with this — expected on shutdown.
            }
            catch (Exception e)
            {
                Debug.LogWarning($"AudioPlaybackReceiver: dropped a chunk: {e.Message}");
            }
        }
    }

    static byte[] ReadFramedChunk(NetworkStream stream)
    {
        var lenBytes = ReadExact(stream, 4);
        // Big-endian, matching struct.pack(">I", ...) on the Python side.
        int length = (lenBytes[0] << 24) | (lenBytes[1] << 16) | (lenBytes[2] << 8) | lenBytes[3];
        return ReadExact(stream, length);
    }

    static byte[] ReadExact(NetworkStream stream, int count)
    {
        var buf = new byte[count];
        int read = 0;
        while (read < count)
        {
            int n = stream.Read(buf, read, count - read);
            if (n == 0) throw new IOException("connection closed mid-frame");
            read += n;
        }
        return buf;
    }

    void Update()
    {
        // Play one at a time, in arrival order, so sentences don't overlap into noise.
        if (_source.isPlaying) return;
        if (_pending.TryDequeue(out var clip))
        {
            _source.clip = clip;
            _source.Play();
        }
    }
}

/// <summary>Minimal WAV (PCM) -> AudioClip decoder. Just enough for Edge-TTS/RVC output.</summary>
public static class WavUtility
{
    public static AudioClip ToAudioClip(byte[] wav)
    {
        if (wav == null || wav.Length < 44 || wav[0] != 'R' || wav[1] != 'I' || wav[2] != 'F' || wav[3] != 'F')
            return null;

        int channels = 1, sampleRate = 48000, bitsPerSample = 16;
        int dataOffset = -1, dataLength = 0;

        int pos = 12; // past "RIFF" size "WAVE"
        while (pos + 8 <= wav.Length)
        {
            string chunkId = System.Text.Encoding.ASCII.GetString(wav, pos, 4);
            int chunkSize = BitConverter.ToInt32(wav, pos + 4);
            int chunkDataStart = pos + 8;

            if (chunkId == "fmt ")
            {
                channels = BitConverter.ToInt16(wav, chunkDataStart + 2);
                sampleRate = BitConverter.ToInt32(wav, chunkDataStart + 4);
                bitsPerSample = BitConverter.ToInt16(wav, chunkDataStart + 14);
            }
            else if (chunkId == "data")
            {
                dataOffset = chunkDataStart;
                dataLength = chunkSize;
            }

            pos = chunkDataStart + chunkSize + (chunkSize % 2); // chunks are word-aligned
        }

        if (dataOffset < 0 || bitsPerSample != 16) return null; // Edge-TTS/RVC output is 16-bit PCM

        int sampleCount = dataLength / 2;
        var samples = new float[sampleCount];
        for (int i = 0; i < sampleCount; i++)
            samples[i] = BitConverter.ToInt16(wav, dataOffset + i * 2) / 32768f;

        var clip = AudioClip.Create("MikuReply", sampleCount / channels, channels, sampleRate, false);
        clip.SetData(samples, 0);
        return clip;
    }
}

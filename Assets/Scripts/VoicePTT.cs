using System.Net;
using System.Net.Sockets;
using UnityEngine;

/// <summary>
/// Push-to-talk over the controller: holding A (right) or X (left) — OVRInput.Button.One is
/// the controller-agnostic alias for both — sends a 1-byte UDP signal to tools/voice_input.py
/// on the PC (1 = start recording, 0 = stop), replacing its old Enter-key gating.
/// Same host:new-port pattern as <see cref="TargetSender"/>'s reverse channel.
/// </summary>
public class VoicePTT : MonoBehaviour
{
    [SerializeField] string host = "172.16.1.25";
    [SerializeField] int port = 5007;

    UdpClient _udp;
    IPEndPoint _endPoint;
    bool _recording;

    void Awake()
    {
        _udp = new UdpClient();
        _endPoint = new IPEndPoint(IPAddress.Parse(host), port);
    }

    void OnDestroy() => _udp?.Close();

    void Update()
    {
        if (OVRInput.GetDown(OVRInput.Button.One)) Send(1);
        else if (OVRInput.GetUp(OVRInput.Button.One)) Send(0);
    }

    void Send(byte b)
    {
        if (b == 1 && _recording) return;
        if (b == 0 && !_recording) return;
        _recording = b == 1;
        _udp.Send(new[] { b }, 1, _endPoint);
        Debug.Log($"VoicePTT: {(b == 1 ? "start" : "stop")} -> {host}:{port}");
    }
}

package id.bsp.frontend.controller;

import id.bsp.frontend.entity.NotifLangganan;
import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.NotifLanggananRepository;
import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.EmailService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseBody;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Forwards device alerts from the Python poller to that device's subscribers.
 *   Python: knows which device has a problem (sends its device_id)
 *   Java:   knows WHO subscribes to it, and how to send
 * Opt-out by default: with no subscribers, no email is sent, which is not a failure, so the poller is not asked to retry.
 * Security: the poller is a program with no login session, so this path accepts calls only from this computer (127.0.0.1); other machines are refused.
 */
@Controller
public class NotifikasiInternalController {

    private final UserRepository users;
    private final NotifLanggananRepository langganan;
    private final EmailService email;
    private final AuditService audit;

    public NotifikasiInternalController(UserRepository users,
                                        NotifLanggananRepository langganan,
                                        EmailService email, AuditService audit) {
        this.users = users;
        this.langganan = langganan;
        this.email = email;
        this.audit = audit;
    }

    private boolean dariKomputerIni(HttpServletRequest req) {
        String asal = req.getRemoteAddr();
        return "127.0.0.1".equals(asal) || "0:0:0:0:0:0:0:1".equals(asal)
                || "::1".equals(asal);
    }

    @PostMapping("/internal/notifikasi-device")
    @ResponseBody
    public ResponseEntity<Object> teruskan(@RequestBody Map<String, String> badan,
                                           HttpServletRequest req) {
        if (!dariKomputerIni(req)) {
            audit.log("poller", AuditService.NOTIF_SENT, null,
                    "panggilan notifikasi ditolak dari " + req.getRemoteAddr(),
                    req.getRemoteAddr(), null, false);
            return ResponseEntity.status(HttpStatus.FORBIDDEN)
                    .body(Map.of("error", "hanya menerima panggilan dari komputer ini"));
        }

        String subjek = badan.getOrDefault("subjek", "[NSM] Peringatan device");
        String isi = badan.getOrDefault("isi", "");
        String device = badan.getOrDefault("device", "-");
        Long deviceId = null;
        try {
            deviceId = Long.valueOf(badan.getOrDefault("device_id", ""));
        } catch (NumberFormatException ignore) {
        }

        List<String> berhasil = new ArrayList<>();
        List<String> gagal = new ArrayList<>();
        int pelanggan = 0;

        if (deviceId != null) {
            for (NotifLangganan sub : langganan.findByDeviceId(deviceId)) {
                User u = users.findByUsername(sub.getUsername()).orElse(null);
                // Disabled or pending accounts are skipped even if still subscribed.
                if (u == null || !u.isEnabled()) continue;
                if (u.getEmail() == null || u.getEmail().isBlank()) continue;
                pelanggan++;
                try {
                    email.kirim(u.getEmail(), subjek, isi);
                    berhasil.add(u.getUsername());
                } catch (Exception e) {
                    // One bad address must not block the others.
                    gagal.add(u.getUsername() + " (" + e.getMessage() + ")");
                }
            }
        }

        // The Target column holds the device ID, like every other device action; the name goes in Detail, and the audit page translates ids to names.
        String targetId = deviceId != null ? String.valueOf(deviceId) : null;

        // Zero subscribers is not a failure, but also not "alert sent"; it is recorded distinctly so it is not read as an email reaching someone.
        boolean dilewati = pelanggan == 0;
        String keterangan = dilewati
                ? "peringatan device \"" + device + "\" tidak dikirim: belum ada "
                  + "user yang berlangganan device ini di halaman Atur Notifikasi"
                : "peringatan device \"" + device + "\" dikirim ke " + berhasil.size()
                  + " dari " + pelanggan + " pelanggan"
                  + (gagal.isEmpty() ? "" : ", gagal: " + String.join("; ", gagal));

        audit.log("sistem", AuditService.NOTIF_SENT, targetId, keterangan,
                req.getRemoteAddr(), null, gagal.isEmpty(),
                dilewati ? AuditService.HASIL_DILEWATI : null);

        // Subscribers exist but none was sent -> ask the poller to retry.
        if (berhasil.isEmpty() && pelanggan > 0) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("terkirim", 0, "pelanggan", pelanggan, "gagal", gagal));
        }
        // Includes the zero-customer case: succeeds as "empty" and the poller marks it done.
        return ResponseEntity.ok(Map.of(
                "terkirim", berhasil.size(),
                "pelanggan", pelanggan,
                "penerima", berhasil,
                "gagal", gagal));
    }

    /**
     * Tiered notifications: ONE email for MANY devices (shared queue, docs/design/TIERED-NOTIFICATIONS.md).
     * Unlike {@link #teruskan}, the body carries device_ids (a list). Recipients are the UNION of subscribers across all listed devices, deduplicated by username so a user subscribed to 3 affected devices gets one email, not three.
     */
    @PostMapping("/internal/notifikasi-gabungan")
    @ResponseBody
    public ResponseEntity<Object> teruskanGabungan(@RequestBody Map<String, Object> badan,
                                                    HttpServletRequest req) {
        if (!dariKomputerIni(req)) {
            audit.log("poller", AuditService.NOTIF_SENT, null,
                    "panggilan notifikasi gabungan ditolak dari " + req.getRemoteAddr(),
                    req.getRemoteAddr(), null, false);
            return ResponseEntity.status(HttpStatus.FORBIDDEN)
                    .body(Map.of("error", "hanya menerima panggilan dari komputer ini"));
        }

        String subjek = String.valueOf(badan.getOrDefault("subjek", "[NSM] Peringatan device"));
        String isi = String.valueOf(badan.getOrDefault("isi", ""));

        List<Long> deviceIds = new ArrayList<>();
        Object mentah = badan.get("device_ids");
        if (mentah instanceof List<?> daftar) {
            for (Object o : daftar) {
                try {
                    deviceIds.add(Long.valueOf(String.valueOf(o)));
                } catch (NumberFormatException ignore) {
                }
            }
        }

        // UNION of subscribers across devices, deduplicated by username. LinkedHashSet keeps a stable order for logs and audit.
        Set<String> usernameUnik = new LinkedHashSet<>();
        if (!deviceIds.isEmpty()) {
            for (NotifLangganan sub : langganan.findByDeviceIdIn(deviceIds)) {
                usernameUnik.add(sub.getUsername());
            }
        }

        List<String> berhasil = new ArrayList<>();
        List<String> gagal = new ArrayList<>();
        int pelanggan = 0;

        for (String username : usernameUnik) {
            User u = users.findByUsername(username).orElse(null);
            if (u == null || !u.isEnabled()) continue;
            if (u.getEmail() == null || u.getEmail().isBlank()) continue;
            pelanggan++;
            try {
                email.kirim(u.getEmail(), subjek, isi);
                berhasil.add(u.getUsername());
            } catch (Exception e) {
                gagal.add(u.getUsername() + " (" + e.getMessage() + ")");
            }
        }

        String targetId = deviceIds.stream().map(String::valueOf)
                .collect(Collectors.joining(","));
        boolean dilewati = pelanggan == 0;
        String keterangan = dilewati
                ? "peringatan gabungan (" + deviceIds.size() + " device) tidak dikirim: "
                  + "belum ada user yang berlangganan device-device ini"
                : "peringatan gabungan (" + deviceIds.size() + " device) dikirim ke "
                  + berhasil.size() + " dari " + pelanggan + " pelanggan unik"
                  + (gagal.isEmpty() ? "" : ", gagal: " + String.join("; ", gagal));

        audit.log("sistem", AuditService.NOTIF_SENT, targetId, keterangan,
                req.getRemoteAddr(), null, gagal.isEmpty(),
                dilewati ? AuditService.HASIL_DILEWATI : null);

        if (berhasil.isEmpty() && pelanggan > 0) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("terkirim", 0, "pelanggan", pelanggan, "gagal", gagal));
        }
        return ResponseEntity.ok(Map.of(
                "terkirim", berhasil.size(),
                "pelanggan", pelanggan,
                "penerima", berhasil,
                "gagal", gagal));
    }
}

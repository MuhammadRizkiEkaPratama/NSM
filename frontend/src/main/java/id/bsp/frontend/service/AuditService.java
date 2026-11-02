package id.bsp.frontend.service;

import id.bsp.frontend.entity.AuditLog;
import id.bsp.frontend.repository.AuditLogRepository;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;

/** Central audit logging. Writes are wrapped in try/catch: an audit failure must never fail the main flow. */
@Service
public class AuditService {

    public static final String LOGIN_SUCCESS   = "LOGIN_SUCCESS";
    public static final String LOGIN_FAILED    = "LOGIN_FAILED";
    public static final String LOGIN_BLOCKED_LOCKED  = "LOGIN_BLOCKED_LOCKED";
    public static final String LOGIN_BLOCKED_PENDING = "LOGIN_BLOCKED_PENDING";
    public static final String LOGIN_BLOCKED_IP      = "LOGIN_BLOCKED_IP";       // IP diblokir
    public static final String LOGOUT          = "LOGOUT";
    // Emergency path: login validated against MySQL because LDAP is unreachable. "Used" and
    // "rejected" are separate actions because they mean very different things when read later.
    public static final String LOGIN_DARURAT         = "LOGIN_DARURAT";
    public static final String LOGIN_DARURAT_DITOLAK = "LOGIN_DARURAT_DITOLAK";
    public static final String SIGNUP          = "SIGNUP";
    public static final String APPROVE_USER    = "APPROVE_USER";
    public static final String REJECT_USER     = "REJECT_USER";
    public static final String UBAH_ROLE       = "USER_ROLE_CHANGE";
    public static final String NONAKTIF_USER   = "USER_DISABLE";
    public static final String AKTIFKAN_USER   = "USER_ENABLE";
    public static final String HAPUS_USER      = "USER_DELETE";
    public static final String LOCKOUT_L1      = "LOCKOUT_L1_FREEZE";
    public static final String LOCKOUT_L2      = "LOCKOUT_L2_EMAIL";
    public static final String LOCKOUT_L3      = "LOCKOUT_L3_IPBLOCK";
    public static final String UNBLOCK_IP      = "UNBLOCK_IP";
    public static final String RESET_LOCKOUT   = "RESET_LOCKOUT";
    public static final String PASSWORD_CHANGE = "PASSWORD_CHANGE";
    public static final String PASSWORD_RESET  = "PASSWORD_RESET";
    public static final String FORGOT_REQUEST  = "FORGOT_REQUEST";
    public static final String VIEW_DEVICE     = "VIEW_DEVICE_DETAIL";
    /*
     * Device notification toggled by an admin (target is the device id) and alert sent by the poller
     * (target is the device name) are separate actions, so filtering by action does not mix them.
     * Legacy rows keep the old name DEVICE_NOTIFY, which stays selectable in the filter.
     */
    public static final String NOTIF_TOGGLE    = "DEVICE_NOTIFY_TOGGLE"; // admin menyalakan/mematikan notifikasi device
    public static final String NOTIF_SENT      = "DEVICE_NOTIFY_SENT";   // poller mengirim peringatan device
    public static final String NOTIF_PREF      = "NOTIF_PREF";           // user ubah langganan notifikasi
    public static final String EMAIL_CHANGE    = "EMAIL_CHANGE";
    public static final String DEVICE_JEDA     = "DEVICE_PAUSE";         // pemantauan dijeda
    public static final String DEVICE_LANJUT   = "DEVICE_RESUME";        // pemantauan dilanjutkan
    public static final String EXPORT_REPORT   = "EXPORT_REPORT";        // unduh CSV laporan
    public static final String VIEW_REPORT     = "VIEW_REPORT";          // buka halaman Report
    public static final String VIEW_HISTORY    = "VIEW_DEVICE_HISTORY";  // buka riwayat 1 device
    public static final String VIEW_BACKUP     = "VIEW_BACKUP";          // buka halaman pemantau backup
    public static final String VIEW_TRAFFIC    = "VIEW_TRAFFIC";
    public static final String VIEW_SERVICES   = "VIEW_SERVICES";        // buka halaman layanan
    public static final String VIEW_KESEHATAN  = "VIEW_KESEHATAN";       // buka halaman kesehatan sistem
    public static final String VIEW_KONFIG     = "VIEW_KONFIG";
    // Building a config command is logged even though nothing is sent yet: attempts rejected by
    // validation are the most useful ones to see.
    public static final String PERINTAH_PRATINJAU = "PERINTAH_PREVIEW";

    /*
     * The next three actions change real devices, so they are named separately (send, cancel,
     * save permanently) to make it clear what exactly someone did. PERINTAH_SIMPAN is the heaviest:
     * afterwards a device restart no longer restores the previous state.
     */
    public static final String PERINTAH_KIRIM = "PERINTAH_KIRIM";
    public static final String PERINTAH_PUTUSKAN = "PERINTAH_PUTUSKAN";
    public static final String PERINTAH_SIMPAN = "PERINTAH_SIMPAN";
    // Auto-ban: block / unblock an IP on the device firewall.
    public static final String FIREWALL_BLOKIR = "FIREWALL_BLOKIR";
    public static final String FIREWALL_BUKA_BLOKIR = "FIREWALL_BUKA_BLOKIR";
    public static final String FIREWALL_ACL_BLOKIR = "FIREWALL_ACL_BLOKIR";

    // Changing intent touches no device but is audited: intent decides what may later be sent to real devices.
    public static final String VIEW_SOT   = "VIEW_SOT";
    public static final String SOT_UBAH   = "SOT_UBAH";
    public static final String VIEW_DRIFT = "VIEW_DRIFT";
    public static final String VIEW_PAGAR = "VIEW_PAGAR";
    public static final String VIEW_INSIDEN = "VIEW_INSIDEN";
    // Read-only pages that reveal the real network layout or proposed device actions; their views are audited like VIEW_DRIFT.
    public static final String VIEW_WAWASAN = "VIEW_WAWASAN";
    public static final String VIEW_AGEN    = "VIEW_AGEN_SOC";
    public static final String VIEW_TENANT  = "VIEW_TENANT";

    // Device discovery. All write actions are audited, including scans: a scan sends packets to
    // every address in a subnet and looks like a port scan to anyone reading network logs.
    // PENEMUAN_SETUJUI is the only path from scan results to the `devices` table.
    public static final String VIEW_PENEMUAN     = "VIEW_PENEMUAN";
    public static final String PENEMUAN_PINDAI   = "PENEMUAN_PINDAI";
    public static final String PENEMUAN_SETUJUI  = "PENEMUAN_SETUJUI";
    public static final String PENEMUAN_ABAIKAN  = "PENEMUAN_ABAIKAN";

    // Syslog views are audited: messages can reveal who changed a configuration from where.
    public static final String VIEW_SYSLOG  = "VIEW_SYSLOG";

    public static final String HASIL_DILEWATI  = "DILEWATI";

    /**
     * Actions whose Target column holds a device ID (not a user or IP). The audit page shows
     * "6 (VM testUbuntu)" instead of "6". Translated at display time, not at write time, because
     * device names change and audit writes must not depend on a call to Python.
     */
    public static final java.util.Set<String> AKSI_TARGET_DEVICE = java.util.Set.of(
            VIEW_DEVICE, VIEW_HISTORY, DEVICE_JEDA, DEVICE_LANJUT,
            NOTIF_TOGGLE, NOTIF_SENT);

    private final AuditLogRepository repo;

    public AuditService(AuditLogRepository repo) {
        this.repo = repo;
    }

    /** Core: saves one audit row. Never throws to the caller. */
    public void log(String actor, String action, String target, String detail,
                    String ip, String userAgent, boolean success) {
        log(actor, action, target, detail, ip, userAgent, success, null);
    }

    public void log(String actor, String action, String target, String detail,
                    String ip, String userAgent, boolean success, String hasil) {
        try {
            AuditLog a = new AuditLog();
            a.setHasil(hasil);
            a.setTimestamp(LocalDateTime.now());
            a.setActor(actor == null || actor.isBlank() ? "anonymous" : trim(actor, 64));
            a.setAction(action);
            a.setTarget(trim(target, 128));
            a.setDetail(trim(detail, 512));
            a.setIp(trim(ip, 64));
            a.setUserAgent(trim(userAgent, 512));
            a.setSuccess(success);
            repo.save(a);
        } catch (Exception e) {
            System.out.println(">>> NSM: gagal simpan audit (" + action + "): " + e.getMessage());
        }
    }

    /** Convenience version: actor from the SecurityContext, IP and user-agent from the request. */
    public void logRequest(String action, String target, String detail,
                           boolean success, HttpServletRequest req) {
        log(currentActor(), action, target, detail, clientIp(req), userAgent(req), success);
    }

    public void logAuth(String actor, String action, String target, String detail,
                        String ip, boolean success) {
        log(actor, action, target, detail, ip, null, success);
    }

    // ==== Helper ====
    public static String currentActor() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.isAuthenticated()
                && !"anonymousUser".equals(auth.getName())) {
            return auth.getName();
        }
        return "anonymous";
    }

    public static String clientIp(HttpServletRequest req) {
        if (req == null) return null;
        String xff = req.getHeader("X-Forwarded-For");
        if (xff != null && !xff.isBlank()) {
            return xff.split(",")[0].trim();
        }
        return req.getRemoteAddr();
    }

    public static String userAgent(HttpServletRequest req) {
        return req == null ? null : req.getHeader("User-Agent");
    }

    private static String trim(String s, int max) {
        if (s == null) return null;
        return s.length() <= max ? s : s.substring(0, max);
    }
}

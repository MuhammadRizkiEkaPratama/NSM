package id.bsp.frontend.controller;

import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ResponseBody;

import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * SYSTEM HEALTH page.
 * Almost everything is computed by Python in `kesehatan.py`, including the healthy/warning/danger verdict. Java adds only two things that Python cannot see:
 *   - MySQL, because accounts and the audit log belong to Java.
 *   - The email server, because email is sent from Java with credentials from application.properties.
 * Neither is business logic: only "reachable or not", a fact about the Java process itself.
 * The route is under /admin, so it is ROLE_ADMIN-only: it exposes file paths, disk sizes and the mail host name.
 */
@Controller
public class KesehatanController {

    private final NetmonApiClient api;
    private final AuditService audit;
    private final UserRepository users;

    @Value("${spring.mail.host:}")
    private String smtpHost;

    @Value("${spring.mail.port:587}")
    private int smtpPort;

    /** SMTP check timeout. Deliberately short and different from the real email send timeout (5 s in application.properties): the page refreshes periodically and a hanging check would make it feel broken exactly when it is most needed. */
    private static final int SMTP_TIMEOUT_MS = 2500;

    public KesehatanController(NetmonApiClient api, AuditService audit,
                               UserRepository users) {
        this.api = api;
        this.audit = audit;
        this.users = users;
    }

    @GetMapping("/admin/kesehatan")
    public String halaman(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_KESEHATAN, null,
                "buka halaman Kesehatan Sistem", true, request);
        return "kesehatan";
    }

    /** Page data. Not audited: the page refreshes itself and logging each refresh would flood the Audit Log. */
    @GetMapping("/api/kesehatan")
    @ResponseBody
    public Object data() {
        Map<String, Object> hasil = new LinkedHashMap<>();

        // The Python part. If uvicorn is down this call throws, which is itself the most important answer; the page must stay open and say so.
        try {
            hasil.put("python", api.getKesehatan());
            hasil.put("python_hidup", true);
        } catch (Exception e) {
            hasil.put("python_hidup", false);
            hasil.put("python_galat", ringkasGalat(e));
        }

        hasil.put("mysql", periksaMysql());
        hasil.put("smtp", periksaSmtp());
        return hasil;
    }

    /** Whether MySQL is readable. One count query on the users table proves the connection, credentials and schema. */
    private Map<String, Object> periksaMysql() {
        Map<String, Object> m = new LinkedHashMap<>();
        long mulai = System.nanoTime();
        try {
            long jumlah = users.count();
            m.put("vonis", "sehat");
            m.put("nilai", jumlah + " akun");
            m.put("ms", (System.nanoTime() - mulai) / 1_000_000);
            m.put("ket", "Terbaca. Ini basis data milik Java (akun, audit log, "
                    + "langganan notifikasi), terpisah dari nsm.db milik Python.");
        } catch (Exception e) {
            m.put("vonis", "bahaya");
            m.put("nilai", "tidak terbaca");
            m.put("ket", "MySQL tidak bisa dibaca: " + ringkasGalat(e)
                    + ". Selama begini, login dan audit log tidak berfungsi, "
                    + "sedangkan pemantauan device tetap berjalan karena "
                    + "datanya ada di nsm.db yang terpisah.");
        }
        return m;
    }

    /**
     * Whether the email server is reachable.
     * Only opens a TCP socket; no login and nothing sent, because repeated logins to Gmail with an App Password would make the account look suspicious. Only network reachability is proven, and the page says so.
     */
    private Map<String, Object> periksaSmtp() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("tujuan", smtpHost + ":" + smtpPort);

        if (smtpHost == null || smtpHost.isBlank()) {
            m.put("vonis", "perhatian");
            m.put("nilai", "belum diatur");
            m.put("ket", "spring.mail.host kosong di application.properties, "
                    + "jadi tidak ada email yang bisa dikirim.");
            return m;
        }

        long mulai = System.nanoTime();
        try (Socket s = new Socket()) {
            s.connect(new InetSocketAddress(smtpHost, smtpPort), SMTP_TIMEOUT_MS);
            m.put("vonis", "sehat");
            m.put("nilai", "terjangkau");
            m.put("ms", (System.nanoTime() - mulai) / 1_000_000);
            m.put("ket", "Soket ke " + smtpHost + ":" + smtpPort + " terbuka. "
                    + "Yang dibuktikan baru keterjangkauan jaringan; apakah "
                    + "App Password masih berlaku hanya terbukti dari email "
                    + "yang benar-benar terkirim, dan itu tercatat di Audit Log.");
        } catch (Exception e) {
            m.put("vonis", "bahaya");
            m.put("nilai", "tidak terjangkau");
            m.put("ket", "Tidak bisa membuka soket ke " + smtpHost + ":"
                    + smtpPort + " dalam " + SMTP_TIMEOUT_MS + " ms ("
                    + ringkasGalat(e) + "). Peringatan device tidak akan "
                    + "sampai ke email siapa pun selama ini berlangsung.");
        }
        return m;
    }

    /**
     * Translates network errors into a sentence saying what to do, instead of raw Spring messages such as `I/O error on GET request ...: null`.
     * Checks the whole cause chain, since Spring wraps ConnectException inside ResourceAccessException.
     * Not `private`: tested directly by KesehatanControllerTest.
     */
    String ringkasGalat(Exception e) {
        String jenis = jenisGangguanJaringan(e);
        if (jenis != null) return jenis;

        String pesan = e.getMessage();
        if (pesan == null || pesan.isBlank()) {
            return "gangguan " + e.getClass().getSimpleName()
                    + " tanpa keterangan tambahan";
        }
        // Strip the ": null" Spring appends when the cause has no message.
        pesan = pesan.replaceAll(":\\s*null$", "").trim();
        return pesan.length() > 160 ? pesan.substring(0, 160) + "..." : pesan;
    }

    /**
     * Sentences for the three network failures that actually occur; returns null for any other error so the original message is not replaced by a guess.
     * Deliberately names no process or port: the method serves three checkers (Python, MySQL, mail server), and a confident but wrong message is worse than a raw one.
     */
    private String jenisGangguanJaringan(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause()) {
            if (t instanceof java.net.ConnectException) {
                return "sambungan ditolak, tidak ada yang mendengarkan di alamat itu";
            }
            if (t instanceof java.net.SocketTimeoutException) {
                return "tidak ada jawaban sampai batas waktu habis; alamatnya "
                        + "terjangkau tetapi yang di ujung sana sedang tertahan";
            }
            if (t instanceof java.net.UnknownHostException) {
                return "nama host tidak dikenali";
            }
            if (t == t.getCause()) break;   // penjaga rantai penyebab melingkar
        }
        return null;
    }
}

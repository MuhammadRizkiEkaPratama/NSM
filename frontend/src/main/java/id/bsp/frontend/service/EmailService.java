package id.bsp.frontend.service;

import jakarta.mail.internet.MimeMessage;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.stereotype.Service;

/**
 * NSM email sender. All emails share one HTML shell (header, card, footer); only the body
 * differs. Device emails (down/recovered) have bodies built in Python (notifikasi.py); account
 * emails (reset/change) are built here, keeping device content in Python and account content in Java.
 */
@Service
public class EmailService {

    // BSP brand colour (a lab label only).
    private static final String HIJAU = "#2B6049";

    private final JavaMailSender mailSender;

    @Value("${spring.mail.username}")
    private String from;

    @Value("${nsm.base-url}")
    private String baseUrl;

    public EmailService(JavaMailSender mailSender) {
        this.mailSender = mailSender;
    }

    /**
     * Sends one HTML email. {@code konten} is the body fragment only; {@link #shell} adds the frame.
     * Throws RuntimeException on failure so callers can record it as failed and retry.
     */
    public void kirim(String toEmail, String subjek, String konten) {
        try {
            MimeMessage msg = mailSender.createMimeMessage();
            MimeMessageHelper h = new MimeMessageHelper(msg, false, "UTF-8");
            h.setFrom(from);
            h.setTo(toEmail);
            h.setSubject(subjek);
            h.setText(shell(konten), true); // true = badan berupa HTML
            mailSender.send(msg);
        } catch (Exception e) {
            throw new RuntimeException("gagal mengirim email: " + e.getMessage(), e);
        }
    }


    public void sendResetLink(String toEmail, String username, String token) {
        String link = baseUrl + "/reset?token=" + token;
        String konten =
              judul("Reset password")
            + "<p style=\"margin:0 0 8px;\">Halo <b>" + esc(username) + "</b>,</p>"
            + "<p style=\"margin:0 0 4px;\">Ada permintaan mengatur ulang password akun NSM kamu. "
            + "Klik tombol di bawah untuk membuat password baru. Tautan berlaku 30 menit.</p>"
            + tombol(link, "Buat password baru")
            + catatan("Kalau kamu tidak meminta ini, abaikan email ini. Passwordmu tidak berubah.");
        kirim(toEmail, "NSM - Reset Password", konten);
    }

    public void sendEmailChangeVerify(String toNewEmail, String username, String token) {
        String link = baseUrl + "/account/email/verify?token=" + token;
        String konten =
              judul("Verifikasi email baru")
            + "<p style=\"margin:0 0 8px;\">Halo <b>" + esc(username) + "</b>,</p>"
            + "<p style=\"margin:0 0 4px;\">Ada permintaan mengganti email akun NSM kamu menjadi alamat ini. "
            + "Klik tombol untuk mengonfirmasi. Tautan berlaku 30 menit.</p>"
            + tombol(link, "Konfirmasi email ini")
            + catatan("Kalau kamu tidak meminta ini, abaikan email ini. Email akun tidak akan berubah.");
        kirim(toNewEmail, "NSM - Verifikasi Email Baru", konten);
    }

    public void sendEmailChangeNotice(String toOldEmail, String username, String newEmail) {
        String konten =
              judul("Permintaan ganti email")
            + "<p style=\"margin:0 0 8px;\">Halo <b>" + esc(username) + "</b>,</p>"
            + "<p style=\"margin:0 0 4px;\">Ada permintaan mengganti email akun NSM kamu ke: <b>"
            + esc(newEmail) + "</b>. Perubahan baru berlaku setelah tautan verifikasi di alamat baru diklik.</p>"
            + "<div style=\"background:#fef6e7;border:1px solid #f6d98a;border-radius:6px;"
            + "padding:10px 12px;color:#8a5a00;font-size:13px;margin-top:14px;\">"
            + "Kalau ini bukan kamu, segera ganti password akunmu. Kemungkinan ada orang lain "
            + "yang sedang mengakses akunmu.</div>";
        kirim(toOldEmail, "NSM - Permintaan Ganti Email", konten);
    }


    private String shell(String konten) {
        return "<!DOCTYPE html><html><body style=\"margin:0;padding:0;background:#f2f4f3;\">"
            + "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" "
            + "style=\"background:#f2f4f3;padding:24px 0;\"><tr><td align=\"center\">"
            + "<table role=\"presentation\" width=\"600\" cellpadding=\"0\" cellspacing=\"0\" "
            + "style=\"max-width:600px;width:100%;background:#ffffff;border-radius:8px;"
            + "overflow:hidden;font-family:Arial,Helvetica,sans-serif;\">"
            + "<tr><td style=\"background:" + HIJAU + ";padding:16px 24px;\">"
            + "<span style=\"color:#ffffff;font-size:18px;font-weight:bold;\">NSM</span>"
            + "<span style=\"color:#cfe3d8;font-size:13px;\">&nbsp;&nbsp;Network Status Monitor</span></td></tr>"
            + "<tr><td style=\"padding:24px;color:#1a1a1a;font-size:14px;line-height:1.5;\">"
            + konten + "</td></tr>"
            + "<tr><td style=\"padding:14px 24px;background:#f7f9f8;color:#8a8a8a;font-size:12px;"
            + "border-top:1px solid #eaeceb;\">Email otomatis dari NSM (Network Status Monitor) "
            + "&middot; PT Bumi Siak Pusako, Divisi Network Security.</td></tr>"
            + "</table></td></tr></table></body></html>";
    }

    private String judul(String teks) {
        return "<h2 style=\"margin:0 0 12px;font-size:18px;color:#1a1a1a;\">" + esc(teks) + "</h2>";
    }

    private String tombol(String url, String teks) {
        return "<p style=\"margin:20px 0 6px;\"><a href=\"" + url + "\" "
            + "style=\"display:inline-block;background:" + HIJAU + ";color:#ffffff;"
            + "text-decoration:none;font-size:14px;font-weight:bold;padding:10px 22px;"
            + "border-radius:6px;\">" + esc(teks) + "</a></p>";
    }

    private String catatan(String teks) {
        return "<p style=\"color:#6b7280;font-size:13px;margin:12px 0 0;\">" + esc(teks) + "</p>";
    }

    /** Prevent special characters from breaking the layout or being injected into the HTML. */
    private static String esc(String s) {
        if (s == null) return "";
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }
}

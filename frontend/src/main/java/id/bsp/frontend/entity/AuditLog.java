package id.bsp.frontend.entity;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/**
 * One audit log row: who did what, when, from which IP, with what outcome.
 * `hasil` ("OK", "GAGAL", "DILEWATI") exists next to `success` because some events are neither
 * success nor failure (e.g. an alert sent to nobody because no one subscribed). Older rows have
 * NULL there and the UI falls back to `success`.
 */
@Entity
@Table(name = "audit_logs", indexes = {
        @Index(name = "idx_audit_ts", columnList = "timestamp"),
        @Index(name = "idx_audit_action", columnList = "action"),
        @Index(name = "idx_audit_actor", columnList = "actor"),
        @Index(name = "idx_audit_target", columnList = "target")
})
public class AuditLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private LocalDateTime timestamp;

    @Column(nullable = false, length = 64)
    private String actor;

    @Column(nullable = false, length = 48)
    private String action;

    @Column(length = 128)
    private String target;

    @Column(length = 512)
    private String detail;

    @Column(length = 64)
    private String ip;

    @Column(name = "user_agent", length = 512)
    private String userAgent;

    @Column(nullable = false)
    private boolean success;

    @Column(length = 16)
    private String hasil;

    public AuditLog() { }

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public LocalDateTime getTimestamp() { return timestamp; }
    public void setTimestamp(LocalDateTime timestamp) { this.timestamp = timestamp; }

    public String getActor() { return actor; }
    public void setActor(String actor) { this.actor = actor; }

    public String getAction() { return action; }
    public void setAction(String action) { this.action = action; }

    public String getTarget() { return target; }
    public void setTarget(String target) { this.target = target; }

    public String getDetail() { return detail; }
    public void setDetail(String detail) { this.detail = detail; }

    public String getIp() { return ip; }
    public void setIp(String ip) { this.ip = ip; }

    public String getUserAgent() { return userAgent; }
    public void setUserAgent(String userAgent) { this.userAgent = userAgent; }

    public boolean isSuccess() { return success; }
    public void setSuccess(boolean success) { this.success = success; }

    public String getHasil() { return hasil; }
    public void setHasil(String hasil) { this.hasil = hasil; }

    public String getHasilTeks() {
        if (hasil != null && !hasil.isBlank()) return hasil;
        return success ? "OK" : "GAGAL";
    }
}

package id.bsp.frontend.entity;

import jakarta.persistence.*;
import java.time.LocalDateTime;

/** Blocked IPs (level 3 lockout). Only an admin can remove an entry (unblock). */
@Entity
@Table(name = "blocked_ips")
public class BlockedIp {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, nullable = false)
    private String ip;

    private String triggeredBy;

    @Column(nullable = false)
    private LocalDateTime blockedAt;

    public BlockedIp() { }

    public BlockedIp(String ip, String triggeredBy, LocalDateTime blockedAt) {
        this.ip = ip;
        this.triggeredBy = triggeredBy;
        this.blockedAt = blockedAt;
    }

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getIp() { return ip; }
    public void setIp(String ip) { this.ip = ip; }

    public String getTriggeredBy() { return triggeredBy; }
    public void setTriggeredBy(String triggeredBy) { this.triggeredBy = triggeredBy; }

    public LocalDateTime getBlockedAt() { return blockedAt; }
    public void setBlockedAt(LocalDateTime blockedAt) { this.blockedAt = blockedAt; }
}

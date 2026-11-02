package id.bsp.frontend.entity;

import jakarta.persistence.*;

/**
 * Email notification subscription per (user, device). One row means subscribed; no row means not
 * subscribed (opt-out by default). `device_id` refers to the device id in Python's SQLite; Java
 * has no device table of its own.
 */
@Entity
@Table(name = "notif_langganan",
       uniqueConstraints = @UniqueConstraint(columnNames = {"username", "device_id"}))
public class NotifLangganan {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private String username;

    @Column(name = "device_id", nullable = false)
    private Long deviceId;

    public NotifLangganan() { }

    public NotifLangganan(String username, Long deviceId) {
        this.username = username;
        this.deviceId = deviceId;
    }

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }

    public Long getDeviceId() { return deviceId; }
    public void setDeviceId(Long deviceId) { this.deviceId = deviceId; }
}

package id.bsp.frontend.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public class DeviceDto {
    public Integer id;
    public String name;
    @JsonProperty("ip_address")
    public String ipAddress;
    @JsonProperty("device_type")
    public String deviceType;
    public String platform;
    public String location;
    /** false = monitoring of this device is paused (the poller skips it). */
    public Boolean aktif;
    /**
     * Why paused, since when, and by whom. Required even though Java does not use them: Jackson
     * silently drops unknown JSON fields, so a missing field never reaches the browser.
     */
    @JsonProperty("jeda_alasan")
    public String jedaAlasan;
    @JsonProperty("jeda_sejak")
    public String jedaSejak;
    @JsonProperty("jeda_oleh")
    public String jedaOleh;
    public Boolean penting;
    @JsonProperty("is_reachable")
    public Boolean isReachable;
    @JsonProperty("response_time_ms")
    public Double responseTimeMs;
    @JsonProperty("last_checked")
    public String lastChecked;
}

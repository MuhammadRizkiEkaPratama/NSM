package id.bsp.frontend;

// Jackson 3 (Spring Boot 4): ObjectMapper is in `tools.jackson` while the annotations stay in `com.fasterxml.jackson.annotation`; both are intended.
import tools.jackson.databind.ObjectMapper;
import id.bsp.frontend.controller.DashboardController;
import id.bsp.frontend.dto.DeviceDto;
import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.mock.web.MockHttpServletRequest;

import java.security.Principal;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Pause-reason tests on the Java side. Java only forwards Python's JSON, but `DeviceDto` has a fixed shape and Jackson silently drops unknown fields, so a pause reason could vanish unnoticed. The pauser's name comes from the session, not the request body, because the body can be forged. */
class JedaAlasanTest {

    private final ObjectMapper json = new ObjectMapper();

    /** The reason from Python must reach `DeviceDto`, not be dropped. */
    @Test
    void alasanJedaTidakHilangSaatJsonDipetakanKeDto() throws Exception {
        String dariPython = """
            {"id": 3, "name": "Gateway WiFi", "ip_address": "192.168.1.1",
             "device_type": "router", "platform": null, "location": "Rumah",
             "aktif": false, "penting": true, "is_reachable": null,
             "response_time_ms": null, "last_checked": "2026-08-08T10:00:00",
             "jeda_alasan": "sedang di luar lokasi",
             "jeda_sejak": "2026-07-30T09:15:00",
             "jeda_oleh": "admin"}
            """;

        DeviceDto d = json.readValue(dariPython, DeviceDto.class);

        assertEquals("sedang di luar lokasi", d.jedaAlasan,
                "alasan jeda dibuang Jackson: field-nya belum didaftarkan di DeviceDto");
        assertEquals("2026-07-30T09:15:00", d.jedaSejak);
        assertEquals("admin", d.jedaOleh);
    }

    /** It must also survive serialization back to the browser as `jeda_alasan`; app.js reads that name. */
    @Test
    void alasanJedaTetapBernamaSamaSaatDikirimKePeramban() throws Exception {
        DeviceDto d = new DeviceDto();
        d.id = 3;
        d.name = "Gateway WiFi";
        d.aktif = false;
        d.jedaAlasan = "sedang di luar lokasi";
        d.jedaSejak = "2026-07-30T09:15:00";
        d.jedaOleh = "admin";

        String keluar = json.writeValueAsString(d);

        assertTrue(keluar.contains("\"jeda_alasan\""),
                "app.js membaca d.jeda_alasan, bukan d.jedaAlasan: " + keluar);
        assertTrue(keluar.contains("\"jeda_sejak\""), keluar);
        assertTrue(keluar.contains("\"jeda_oleh\""), keluar);
    }

    /** A device that is not paused must not carry a reason. */
    @Test
    void deviceTidakDijedaTidakPunyaAlasan() throws Exception {
        String dariPython = """
            {"id": 1, "name": "Laptop", "aktif": true,
             "jeda_alasan": null, "jeda_sejak": null, "jeda_oleh": null}
            """;
        DeviceDto d = json.readValue(dariPython, DeviceDto.class);
        assertNull(d.jedaAlasan);
        assertNull(d.jedaSejak);
        assertNull(d.jedaOleh);
    }

    /** The controller forwards the reason to Python unchanged. */
    @Test
    void controllerMeneruskanAlasanKePython() {
        NetmonApiClient api = mock(NetmonApiClient.class);
        AuditService audit = mock(AuditService.class);
        when(api.setDeviceAktif(anyInt(), anyBoolean(), any(), any())).thenReturn(Map.of("ok", true));

        Map<String, Object> badan = new HashMap<>();
        badan.put("aktif", false);
        badan.put("alasan", "VM dimatikan untuk snapshot");

        Principal siapa = () -> "admin";
        new DashboardController(api, audit)
                .setAktif(3, badan, new MockHttpServletRequest(), siapa);

        ArgumentCaptor<String> alasan = ArgumentCaptor.forClass(String.class);
        verify(api).setDeviceAktif(anyInt(), anyBoolean(), alasan.capture(), anyString());
        assertEquals("VM dimatikan untuk snapshot", alasan.getValue());
    }

    /** The pauser's name comes from the session; the name sent by the browser is ignored. */
    @Test
    void namaPenjedaDariSesiBukanDariBadanPermintaan() {
        NetmonApiClient api = mock(NetmonApiClient.class);
        AuditService audit = mock(AuditService.class);
        when(api.setDeviceAktif(anyInt(), anyBoolean(), any(), any())).thenReturn(Map.of("ok", true));

        Map<String, Object> badan = new HashMap<>();
        badan.put("aktif", false);
        badan.put("alasan", "coba-coba");
        badan.put("oleh", "hacker");

        Principal siapa = () -> "admin";
        new DashboardController(api, audit)
                .setAktif(3, badan, new MockHttpServletRequest(), siapa);

        ArgumentCaptor<String> oleh = ArgumentCaptor.forClass(String.class);
        verify(api).setDeviceAktif(anyInt(), anyBoolean(), anyString(), oleh.capture());
        assertEquals("admin", oleh.getValue(),
                "nama penjeda diambil dari badan permintaan: siapa pun bisa mengaku jadi orang lain");
    }

    /** The reason may be empty without failing the request; the empty path must work, including in the API client (do not build the body with Map.of()). */
    @Test
    void alasanBolehKosong() {
        NetmonApiClient api = mock(NetmonApiClient.class);
        AuditService audit = mock(AuditService.class);
        when(api.setDeviceAktif(anyInt(), anyBoolean(), any(), any())).thenReturn(Map.of("ok", true));

        Map<String, Object> badan = new HashMap<>();
        badan.put("aktif", false);

        Principal siapa = () -> "admin";
        new DashboardController(api, audit)
                .setAktif(3, badan, new MockHttpServletRequest(), siapa);

        ArgumentCaptor<String> alasan = ArgumentCaptor.forClass(String.class);
        verify(api).setDeviceAktif(anyInt(), anyBoolean(), alasan.capture(), anyString());
        assertNull(alasan.getValue(), "alasan yang tidak dikirim harus jadi null, bukan \"null\"");
    }
}

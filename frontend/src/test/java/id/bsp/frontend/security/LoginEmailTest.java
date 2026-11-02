package id.bsp.frontend.security;

import org.junit.jupiter.api.Test;
import org.springframework.ldap.core.DirContextOperations;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** Tests the bridge between the typed name and the directory uid. Groups are `posixGroup` with plain-uid `memberUid`, and the filter `(memberUid={1})` is filled with what the user TYPED. With email login, `arif@bsp.id` matches nothing: the bind succeeds but zero roles are found, and login is refused with a misleading "no NSM group" message. */
class LoginEmailTest {

    private DirContextOperations entri(String uid) {
        DirContextOperations e = mock(DirContextOperations.class);
        when(e.getStringAttribute("uid")).thenReturn(uid);
        return e;
    }

    /** Core fix: the user types an email, the lookup still uses the uid. */
    @Test
    void loginPakaiEmailTetapMencariGrupPakaiUid() {
        assertEquals("rina",
                LdapConfig.uidUntukGrup(entri("rina"), "rina@bsp.id"),
                "pencarian grup memakai email; orang ini akan dapat nol peran "
                + "walau sandinya benar dan grupnya ada");
    }

    @Test
    void loginPakaiUidTidakBerubah() {
        assertEquals("rina",
                LdapConfig.uidUntukGrup(entri("rina"), "rina"));
    }

    /** Case is normalized too: LDAP search is case-insensitive but `memberUid` is compared exactly, so the uid is taken from the entry. */
    @Test
    void hurufBesarKecilIkutDibenarkan() {
        assertEquals("rina",
                LdapConfig.uidUntukGrup(entri("rina"), "RINA@BSP.ID"));
    }

    /** An entry without a `uid` attribute falls back to the typed name rather than throwing a NullPointerException mid-login. */
    @Test
    void entriTanpaUidJatuhKeYangDiketik() {
        assertEquals("rina", LdapConfig.uidUntukGrup(entri(null), "rina"));
        assertEquals("rina", LdapConfig.uidUntukGrup(entri("  "), "rina"));
        assertEquals("rina", LdapConfig.uidUntukGrup(null, "rina"));
    }
}

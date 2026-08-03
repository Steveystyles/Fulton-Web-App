import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, type Announcement, type User } from "../lib/api";

type AuthContextValue = {
  user: User | null;
  availableAnnouncements: Announcement[];
  pendingAnnouncements: Announcement[];
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  updateUser: (user: User) => void;
  acknowledgeAnnouncement: (
    campaignId: string,
    action: "played" | "dismissed",
  ) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

type AuthProviderProps = {
  children: ReactNode;
};

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [availableAnnouncements, setAvailableAnnouncements] = useState<Announcement[]>([]);
  const [pendingAnnouncements, setPendingAnnouncements] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    try {
      const response = await api.me();
      setUser(response.user);
      setAvailableAnnouncements(response.availableAnnouncements ?? []);
      setPendingAnnouncements(response.pendingAnnouncements);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
        setAvailableAnnouncements([]);
        setPendingAnnouncements([]);
        return;
      }
      throw error;
    }
  }, []);

  useEffect(() => {
    let active = true;

    async function loadSession() {
      try {
        const response = await api.me();
        if (active) {
          setUser(response.user);
          setAvailableAnnouncements(response.availableAnnouncements ?? []);
          setPendingAnnouncements(response.pendingAnnouncements);
        }
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) {
          console.error(error);
        }
        if (active) {
          setUser(null);
          setAvailableAnnouncements([]);
          setPendingAnnouncements([]);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadSession();

    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const response = await api.login(username, password);
    setUser(response.user);
    setAvailableAnnouncements(response.availableAnnouncements ?? []);
    setPendingAnnouncements(response.pendingAnnouncements);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      setAvailableAnnouncements([]);
      setPendingAnnouncements([]);
    }
  }, []);

  const acknowledgeAnnouncement = useCallback(
    async (campaignId: string, action: "played" | "dismissed") => {
      await api.acknowledgeAnnouncement(campaignId, action);
      setPendingAnnouncements((current) =>
        current.filter((announcement) => announcement.id !== campaignId),
      );
    },
    [],
  );

  const value = useMemo(
    () => ({
      user,
      availableAnnouncements,
      pendingAnnouncements,
      loading,
      login,
      logout,
      refreshUser,
      updateUser: setUser,
      acknowledgeAnnouncement,
    }),
    [
      acknowledgeAnnouncement,
      availableAnnouncements,
      loading,
      login,
      logout,
      pendingAnnouncements,
      refreshUser,
      user,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return context;
}

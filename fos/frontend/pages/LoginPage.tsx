import { FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowRight, AtSign, LockKeyhole } from "lucide-react";

import { apiClient } from "../services/client";
import { useAuthStore } from "../store/auth";
import "../styles/routes/auth.css";

type LoginResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation() as { state?: { from?: { pathname?: string } } };
  const setSession = useAuthStore((state) => state.setSession);
  const updateTokens = useAuthStore((state) => state.updateTokens);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const loginRes = await apiClient.post<LoginResponse>("/auth/login", {
        email,
        password,
      });
      const { access_token, refresh_token } = loginRes.data;
      updateTokens(access_token, refresh_token);

      const meRes = await apiClient.get("/auth/me");
      setSession({
        accessToken: access_token,
        refreshToken: refresh_token,
        user: meRes.data,
      });
      const redirectTo = location.state?.from?.pathname ?? "/dashboard";
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setError(t('auth.login.invalid'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="ss-auth__card ss-auth__login-card">
      <div className="ss-auth__login-intro">
        <div className="ss-auth__hero-badge">
          <span className="ss-auth__hero-badge-dot" />
          {t("auth.login.badge")}
        </div>

        <div className="space-y-2">
          <h2 className="ss-auth__title">
            {t("auth.login.welcome")}
          </h2>
          <p className="ss-auth__copy">
            {t("auth.login.subtitle")}
          </p>
        </div>
      </div>

      <form onSubmit={onSubmit} className="ss-auth__login-form">
        <div>
          <label htmlFor="login-email" className="ss-auth__label">
            {t("auth.login.email")}
          </label>
          <div className="ss-auth__field">
            <AtSign size={16} className="ss-auth__field-icon" />
            <input
              id="login-email"
              className="ss-input ss-auth__input"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder={t("auth.login.emailPlaceholder")}
              required
            />
          </div>
        </div>

        <div>
          <label htmlFor="login-password" className="ss-auth__label">
            {t("auth.login.password")}
          </label>
          <div className="ss-auth__field">
            <LockKeyhole size={16} className="ss-auth__field-icon" />
            <input
              id="login-password"
              className="ss-input ss-auth__input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={t("auth.login.passwordPlaceholder")}
              required
            />
          </div>
        </div>

        {error ? (
          <div className="ss-auth__status ss-auth__status--error">
            {t("auth.login.invalid")}
          </div>
        ) : null}

        <button type="submit" className="ss-button w-full justify-between px-5" disabled={loading}>
          <span>{loading ? `${t("auth.login.signin")}…` : t("auth.login.signin")}</span>
          <ArrowRight size={16} />
        </button>
      </form>

      <div className="ss-auth__footer">
        <p className="ss-auth__footer-text">
          {t("auth.login.noAccount")}{" "}
          <Link to="/register" className="ss-auth__footer-link">
            {t("auth.login.create")}
          </Link>
        </p>
      </div>
    </section>
  );
}

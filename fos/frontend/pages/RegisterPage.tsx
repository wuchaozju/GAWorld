import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { apiClient } from "../services/client";
import { useTranslation } from "react-i18next";
import { getBackendErrorDetail } from '@/utils/apiError';
import "../styles/routes/auth.css";

const COUNTRY_CODES = [
  { value: "+86", label: "+86 中国" },
  { value: "+852", label: "+852 中国香港" },
  { value: "+853", label: "+853 中国澳门" },
  { value: "+886", label: "+886 中国台湾" },
  { value: "+1", label: "+1 US/CA" },
  { value: "+44", label: "+44 UK" },
  { value: "+81", label: "+81 日本" },
  { value: "+82", label: "+82 한국" },
  { value: "+65", label: "+65 Singapore" },
];

export function RegisterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    organization: "",
    email: "",
    username: "",
    full_name: "",
    country_code: "+86",
    phone_number: "",
    password: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleChange = (field: string, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const localPhone = String(form.phone_number || "").replace(/\D/g, "").replace(/^0+/, "");
      const phone = `${form.country_code}${localPhone}`;
      const phoneOk = /^\+[1-9]\d{7,14}$/.test(phone);
      if (!phoneOk) {
        setLoading(false);
        setError('invalid_phone');
        return;
      }
      await apiClient.post("/auth/register", {
        organization: form.organization,
        email: form.email,
        username: form.username,
        full_name: form.full_name,
        phone_number: phone,
        password: form.password,
      });
      setSuccess(true);
      setTimeout(() => navigate("/login"), 1500);
    } catch (err: any) {
      const detail = getBackendErrorDetail(err);
      setError(detail !== null ? detail : t('auth.register.failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="panel" style={{ maxWidth: 520, margin: "0 auto", gap: "0.75rem" }}>
      <div className="panel-title">{t('auth.register.title')}</div>
      <form onSubmit={onSubmit} className="card" style={{ gap: "0.5rem" }}>
        <label>
          {t('auth.register.organization')}
          <input className="input" value={form.organization} onChange={(e) => handleChange("organization", e.target.value)} required />
        </label>
        <label>
          {t('auth.register.email')}
          <input className="input" type="email" value={form.email} onChange={(e) => handleChange("email", e.target.value)} required />
        </label>
        <label>
          {t('auth.register.username')}
          <input className="input" value={form.username} onChange={(e) => handleChange("username", e.target.value)} required />
        </label>
        <label>
          {t('auth.register.fullName')}
          <input className="input" value={form.full_name} onChange={(e) => handleChange("full_name", e.target.value)} required />
        </label>
        <label>
          {t('auth.register.phone')}
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <select
              className="input"
              value={form.country_code}
              onChange={(e) => handleChange("country_code", e.target.value)}
              aria-label={t('auth.register.countryCode')}
              style={{ width: 140, flex: "0 0 140px" }}
            >
              {COUNTRY_CODES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <input
              className="input"
              value={form.phone_number}
              onChange={(e) => handleChange("phone_number", e.target.value)}
              required
              inputMode="numeric"
              placeholder={t('auth.register.phonePlaceholder')}
              title={t('auth.register.invalidPhoneTitle') || 'Enter phone digits only'}
              style={{ flex: 1 }}
            />
          </div>
          <div style={{ color: "var(--muted)", fontSize: "0.875rem", marginTop: "0.35rem" }}>
            {t('auth.register.phoneHint')}
          </div>
        </label>
        <label>
          {t('auth.register.password')}
          <input className="input" type="password" value={form.password} onChange={(e) => handleChange("password", e.target.value)} required />
        </label>
        {error === 'invalid_phone' && <div style={{ color: "#f87171" }}>{t('auth.register.invalidPhone')}</div>}
        {error && error !== 'invalid_phone' && (
          <div style={{ color: "#f87171" }}>
            {error === 'register_failed' ? t('auth.register.failed') : `Error: ${String(error).toLowerCase()}`}
          </div>
        )}
        {success && <div style={{ color: "#34d399" }}>{t('auth.register.success')}</div>}
        <button type="submit" className="button" disabled={loading}>
          {loading ? t('auth.register.submit') + '…' : t('auth.register.submit')}
        </button>
      </form>
      <div style={{ color: "var(--muted)" }}>
        {t('auth.register.have')} <Link to="/login">{t('auth.register.signin')}</Link>
      </div>
    </section>
  );
}

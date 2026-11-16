import { useState } from "react";
import {
  ArrowLeft,
  CalendarDays,
  Check,
  Copy,
  ExternalLink,
  Info,
  MessageSquareShare,
  QrCode,
} from "lucide-react";
import { Link } from "react-router-dom";
import meetingQrImage from "../assets/fos-meeting-qr.jpeg";
import groupQrImage from "../assets/fos-wechat-group-qr.jpeg";
import "../styles/routes/product.css";

type MeetingPublishStatus = "pending" | "published";

const RELEASE_PAGE_PATH = "/meeting";

const RELEASE_INFO = {
  title: "FOS 平台线上发布演示会",
  welcome: "欢迎体验 FOS 平台。本页会持续更新最新会议安排、入会方式和二维码信息。",
  expectedTime: "暂定于 2026 年 6 月 21 日 14:00 举行",
  note: "会议时间暂定为 2026 年 6 月 21 日 14:00，可通过下方二维码、会议号或入会链接加入腾讯会议。",
  latestNotice: "会议二维码、会议号和入会链接已更新，请以本页内容为准。",
} as const;

const MEETING_INFO: {
  status: MeetingPublishStatus;
  scheduledTime: string;
  meetingId: string;
  joinLink: string;
  qrImageUrl: typeof meetingQrImage;
  statusLabel: string;
  publishHint: string;
} = {
  status: "published",
  scheduledTime: "2026 年 6 月 21 日 14:00",
  meetingId: "358-469-384",
  joinLink: "https://meeting.tencent.com/dm/TVd7gT8bMN2b",
  qrImageUrl: meetingQrImage,
  statusLabel: "会议信息已发布",
  publishHint: "可扫码加入腾讯会议，也可以使用会议号或入会链接加入。",
};

export function ReleaseDemoPage() {
  const [copied, setCopied] = useState(false);
  const pageUrl =
    typeof window === "undefined" ? RELEASE_PAGE_PATH : new URL(window.location.href).toString();
  const meetingPublished = MEETING_INFO.status === "published";

  const handleCopyPageLink = async (): Promise<void> => {
    if (typeof navigator === "undefined" || !navigator.clipboard) {
      return;
    }
    try {
      await navigator.clipboard.writeText(pageUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch (error) {
      console.error("Failed to copy meeting page link", error);
    }
  };

  return (
    <main className="ss-product-page ss-release-page">
      <section className="ss-release-page__hero">
        <div className="ss-release-page__hero-copy">
          <span className="ss-release-page__eyebrow">FOS Meeting Update</span>
          <h1 className="ss-release-page__title">{RELEASE_INFO.title}</h1>
          <p className="ss-release-page__lead">{RELEASE_INFO.welcome}</p>

          <div className="ss-release-page__meta">
            <span className="ss-release-page__meta-pill">
              <CalendarDays size={16} />
              {RELEASE_INFO.expectedTime}
            </span>
            <span className="ss-release-page__meta-pill ss-release-page__meta-pill--soft">
              <Info size={16} />
              {MEETING_INFO.statusLabel}
            </span>
          </div>

          <p className="ss-release-page__note">{RELEASE_INFO.note}</p>
        </div>

        <div className="ss-release-page__hero-actions">
          <Link to="/" className="ss-release-page__button ss-release-page__button--primary">
            <ArrowLeft size={16} />
            返回平台首页
          </Link>
          <button
            type="button"
            className="ss-release-page__button ss-release-page__button--secondary"
            onClick={() => {
              void handleCopyPageLink();
            }}
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? "已复制页面链接" : "复制页面链接"}
          </button>
        </div>
      </section>

      <section className="ss-release-page__grid" aria-label="meeting update panels">
        <article className="ss-release-page__panel">
          <div className="ss-release-page__panel-head">
            <div>
              <p className="ss-release-page__panel-kicker">交流群</p>
              <h2 className="ss-release-page__panel-title">扫码加入微信群交流讨论</h2>
            </div>
            <span className="ss-release-page__icon-chip">
              <MessageSquareShare size={18} />
            </span>
          </div>

          <div className="ss-release-page__meeting-layout">
            <div className="ss-release-page__qr-frame ss-release-page__qr-frame--meeting">
              <img
                src={groupQrImage}
                alt="FOS 微信群二维码"
                className="ss-release-page__qr-image"
              />
            </div>

            <div className="ss-release-page__meeting-info">
              <div className="ss-release-page__info-row">
                <span className="ss-release-page__info-label">交流用途</span>
                <strong className="ss-release-page__info-value">平台咨询与会议信息同步</strong>
              </div>

              <div className="ss-release-page__info-row">
                <span className="ss-release-page__info-label">入群说明</span>
                <p className="ss-release-page__status-copy">
                  有关于平台的问题咨询、bug反馈，以及及时获取会议的具体信息，可以扫码加群交流讨论。
                </p>
              </div>

              <div className="ss-release-page__status-box">
                <span className="ss-release-page__status-title">适用场景</span>
                <p className="ss-release-page__status-copy">
                  适合咨询平台使用、了解发布会最新安排、交流接入问题与后续实验体验反馈。
                </p>
              </div>
            </div>
          </div>
        </article>

        <article className="ss-release-page__panel">
          <div className="ss-release-page__panel-head">
            <div>
              <p className="ss-release-page__panel-kicker">会议信息</p>
              <h2 className="ss-release-page__panel-title">会议二维码、会议号与入会链接</h2>
            </div>
            <span className="ss-release-page__icon-chip">
              <MessageSquareShare size={18} />
            </span>
          </div>

          <div className="ss-release-page__meeting-layout">
            <div className="ss-release-page__qr-frame ss-release-page__qr-frame--meeting">
              {meetingPublished && MEETING_INFO.qrImageUrl ? (
                <img
                  src={MEETING_INFO.qrImageUrl}
                  alt="会议二维码"
                  className="ss-release-page__qr-image"
                />
              ) : (
                <div className="ss-release-page__placeholder">
                  <QrCode size={34} />
                  <strong>会议二维码稍后发布</strong>
                  <span>{MEETING_INFO.publishHint}</span>
                </div>
              )}
            </div>

            <div className="ss-release-page__meeting-info">
              <div className="ss-release-page__info-row">
                <span className="ss-release-page__info-label">会议时间</span>
                <strong className="ss-release-page__info-value">
                  {meetingPublished && MEETING_INFO.scheduledTime
                    ? MEETING_INFO.scheduledTime
                    : "稍后发布"}
                </strong>
              </div>

              <div className="ss-release-page__info-row">
                <span className="ss-release-page__info-label">会议号</span>
                <strong className="ss-release-page__info-value">
                  {meetingPublished && MEETING_INFO.meetingId ? MEETING_INFO.meetingId : "稍后发布"}
                </strong>
              </div>

              <div className="ss-release-page__info-row">
                <span className="ss-release-page__info-label">入会链接</span>
                {meetingPublished && MEETING_INFO.joinLink ? (
                  <a
                    href={MEETING_INFO.joinLink}
                    target="_blank"
                    rel="noreferrer"
                    className="ss-release-page__inline-link"
                  >
                    打开会议链接
                    <ExternalLink size={15} />
                  </a>
                ) : (
                  <strong className="ss-release-page__info-value">稍后发布</strong>
                )}
              </div>

              <div className="ss-release-page__status-box">
                <span className="ss-release-page__status-title">当前状态</span>
                <p className="ss-release-page__status-copy">
                  {meetingPublished
                    ? "会议接入信息已发布，可直接扫码或使用会议号进入线上发布演示会。"
                    : "当前仍为预告页。等最终时间和接入方式确认后，这里会更新为正式的会议信息。"}
                </p>
              </div>
            </div>
          </div>
        </article>
      </section>
    </main>
  );
}

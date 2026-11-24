import { useState } from "react";
import { Icon } from "../components/Icon.tsx";
import { isReference, payerKey, storageRead } from "../services/demoSession.ts";

export function Help({ payerId }: { payerId?: string }) {
  const reference = payerId ? storageRead("sessionStorage", `${payerKey}:${payerId}`) : "";
  const [copied, setCopied] = useState("");

  return (
    <div className="help-editorial-layout">
      {/* Urgent Cybercrime Helpline Hero Banner */}
      <section className="card emergency-helpline-hero" aria-labelledby="help-heading">
        <div className="helpline-hero-copy">
          <p className="eyebrow">PauseGuard Help &amp; Response</p>
          <h2 id="help-heading">
            Help and <em className="text-accent-italic">fraud reporting.</em>
          </h2>
          <p className="card-lead">
            For a suspicious request, stop the payment and verify independently through a trusted
            contact method. For an actual transfer, contact your bank through its official channel.
          </p>
        </div>

        <div className="emergency-helpline-panel">
          <div className="helpline-left">
            <div className="helpline-badge">
              <Icon name="phone" size={16} />
              <span>National Cybercrime Helpline</span>
            </div>
            <strong className="helpline-number">Dial 1930 (Toll Free)</strong>
            <p className="field-help">
              Operated by the Indian Cyber Crime Coordination Centre (I4C), Ministry of Home
              Affairs.
            </p>
          </div>
          <div className="actions emergency-actions">
            <a className="primary call-helpline-btn" href="tel:1930">
              <Icon name="phone" size={16} /> Call cybercrime helpline 1930
            </a>
            <a
              className="secondary"
              href="https://cybercrime.gov.in/"
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="external" size={16} /> Open the National Cybercrime Reporting Portal
            </a>
          </div>
        </div>
      </section>

      {/* Split Editorial Grid: 4-Step Incident Timeline + Recovery Docket */}
      <div className="help-body-grid">
        <section className="card incident-protocol-card" aria-labelledby="protocol-heading">
          <p className="eyebrow">Response sequence</p>
          <h3 id="protocol-heading">APP Fraud Immediate Action Checklist</h3>
          <ol className="protocol-timeline">
            <li className="protocol-step">
              <span className="step-num">01</span>
              <div>
                <strong>Disconnect &amp; Stop</strong>
                <p>
                  Disconnect high-pressure phone or video calls. Fraudsters exploit artificial
                  urgency to bypass careful verification.
                </p>
              </div>
            </li>
            <li className="protocol-step">
              <span className="step-num">02</span>
              <div>
                <strong>Contact Your Bank</strong>
                <p>
                  Notify your account bank within the initial 2-hour Golden Window to help freeze
                  recipient account trails.
                </p>
              </div>
            </li>
            <li className="protocol-step">
              <span className="step-num">03</span>
              <div>
                <strong>File on 1930 Portal</strong>
                <p>
                  Submit transaction logs, beneficiary UPI VPA, and phone numbers to
                  cybercrime.gov.in.
                </p>
              </div>
            </li>
            <li className="protocol-step">
              <span className="step-num">04</span>
              <div>
                <strong>Preserve Evidence</strong>
                <p>
                  Keep PauseGuard tamper-evident audit references and reason codes ready for
                  official investigation.
                </p>
              </div>
            </li>
          </ol>
        </section>

        {payerId ? (
          <section id="recovery-assist" className="card recovery-assist-panel">
            <div className="recovery-header">
              <span className="symbol mint">
                <Icon name="shieldCheck" size={20} />
              </span>
              <div>
                <p className="eyebrow">Session docket</p>
                <h3>Recovery Assist</h3>
              </div>
            </div>
            <p className="field-help">
              Use your simulated request reference when discussing the demo. Keep actual account
              information in official channels. Reports are submitted directly through the official
              portal.
            </p>

            {isReference(reference) ? (
              <div className="evidence-preview-card">
                <div className="evidence-header">
                  <span className="pill neutral">Simulation Incident Record</span>
                  <span className="field-help">Hash-Chained Mock Log</span>
                </div>
                <p className="reference">
                  <code>{reference}</code>
                </p>
                <div className="actions">
                  <button
                    className="secondary copy-ref-action-btn"
                    type="button"
                    onClick={() => {
                      void (async () => {
                        try {
                          await navigator.clipboard.writeText(reference);
                          setCopied("Reference copied.");
                          setTimeout(() => setCopied(""), 3000);
                        } catch {
                          setCopied("Select and copy the displayed reference.");
                        }
                      })();
                    }}
                  >
                    <Icon name="copy" size={16} /> Copy demo reference
                  </button>
                </div>
                {copied && (
                  <p role="status" className="field-help text-accent">
                    {copied}
                  </p>
                )}
              </div>
            ) : (
              <div className="empty-docket-box">
                <Icon name="fileText" size={18} />
                <p className="field-help no-ref-note">
                  Open a simulated payment in this tab to make its reference available here.
                </p>
              </div>
            )}
          </section>
        ) : (
          <section className="card recovery-assist-panel">
            <div className="recovery-header">
              <span className="symbol mint">
                <Icon name="lock" size={20} />
              </span>
              <div>
                <p className="eyebrow">Independent verification</p>
                <h3>Verify out-of-band</h3>
              </div>
            </div>
            <p className="field-help">
              Never call back a number sent inside a payment prompt or message. Reach your bank,
              family member, or supplier using a contact you saved earlier.
            </p>
            <div className="actions">
              <a className="secondary" href="/payer/login">
                Open payer workspace
              </a>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { ArrowLeft } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { termsDoc, pickLegal, backLabel } from '@/translations/legalContent';

const STYLE_MAP = {
  amber: 'mt-2 text-amber-400 font-semibold',
  red: 'text-red-400 font-semibold',
  cyan: 'text-cyan-400 font-semibold',
};

function Block({ block, language }) {
  if (block.type === 'ul') {
    return (
      <ul className="list-disc list-inside space-y-2 mt-2">
        {block.items.map((item, i) => (
          <li key={i}>{pickLegal(item, language)}</li>
        ))}
      </ul>
    );
  }
  // paragraph
  const cls = block.style ? STYLE_MAP[block.style] || '' : '';
  return <p className={cls}>{pickLegal(block.text, language)}</p>;
}

// Shared renderer used by both Terms and Privacy pages
export function LegalDocument({ doc, language }) {
  const footerWrapStyle = doc.footer?.style === 'amber'
    ? 'p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl'
    : 'p-4 bg-cyan-500/10 border border-cyan-500/30 rounded-xl';
  const footerTextStyle = doc.footer?.style === 'amber' ? 'text-amber-400 font-semibold' : 'text-cyan-400 font-semibold';

  return (
    <>
      <h1 className="text-3xl font-bold mb-6" data-testid="legal-title">{pickLegal(doc.title, language)}</h1>
      <p className="text-text-muted mb-4">{pickLegal(doc.effectiveDate, language)}</p>

      <div className="space-y-6 text-gray-300">
        {doc.sections.map((section, idx) => (
          <section key={idx}>
            <h2 className="text-xl font-bold text-white mb-3">{pickLegal(section.heading, language)}</h2>
            <div className="space-y-1">
              {section.blocks.map((block, bIdx) => (
                <Block key={bIdx} block={block} language={language} />
              ))}
            </div>
          </section>
        ))}

        {doc.footer && (
          <section className={footerWrapStyle}>
            <p className={footerTextStyle}>{pickLegal(doc.footer.text, language)}</p>
          </section>
        )}
      </div>
    </>
  );
}

export default function TermsPage() {
  const navigate = useNavigate();
  const { language } = useLanguage();

  return (
    <div className="min-h-screen bg-void text-white p-6">
      <div className="max-w-3xl mx-auto">
        <Button
          variant="outline"
          onClick={() => navigate(-1)}
          className="mb-6 border-white/10"
          data-testid="terms-back-btn"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          {pickLegal(backLabel, language)}
        </Button>

        <LegalDocument doc={termsDoc} language={language} />
      </div>
    </div>
  );
}

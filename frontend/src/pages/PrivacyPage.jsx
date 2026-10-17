import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { ArrowLeft } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';
import { privacyDoc, pickLegal, backLabel } from '@/translations/legalContent';
import { LegalDocument } from './TermsPage';

export default function PrivacyPage() {
  const navigate = useNavigate();
  const { language } = useLanguage();

  return (
    <div className="min-h-screen bg-void text-white p-6">
      <div className="max-w-3xl mx-auto">
        <Button
          variant="outline"
          onClick={() => navigate(-1)}
          className="mb-6 border-white/10"
          data-testid="privacy-back-btn"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          {pickLegal(backLabel, language)}
        </Button>

        <LegalDocument doc={privacyDoc} language={language} />
      </div>
    </div>
  );
}

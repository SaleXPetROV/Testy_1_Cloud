import { useEffect, useRef, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

/**
 * ImageLightbox — полноэкранный просмотр картинки из чата.
 *
 *  • Границы модалки совпадают с границами фото (обёртка shrink-wrap,
 *    без лишних отступов и панелей).
 *  • Зум: клик / двойной клик по фото или колесо мыши (1x–4x).
 *    В увеличенном состоянии фото панорамируется скроллом внутри рамки.
 *  • Кнопка закрытия — в правом верхнем углу модалки (по границе фото).
 *  • Клик по затемнению или Esc — закрыть.
 *  • Рендерится через portal на document.body — поверх любых модалок
 *    (в т.ч. SupportModal с z-index 10000).
 */
export default function ImageLightbox({ src, onClose, testIdPrefix = 'image' }) {
  const [zoom, setZoom] = useState(1); // 1 = вписано в экран
  const [baseSize, setBaseSize] = useState(null); // {w, h} вписанного изображения
  const imgRef = useRef(null);
  const frameRef = useRef(null);

  // Запоминаем "вписанный" размер один раз при загрузке (зум = 1)
  const handleLoad = useCallback(() => {
    const el = imgRef.current;
    if (el) setBaseSize({ w: el.clientWidth, h: el.clientHeight });
  }, []);

  const toggleZoom = useCallback(() => {
    setZoom((z) => (z > 1 ? 1 : 2.5));
  }, []);

  // Колесо мыши — плавный зум (нужен non-passive listener для preventDefault)
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const onWheel = (e) => {
      e.preventDefault();
      setZoom((z) => {
        const cur = z || 1;
        const next = e.deltaY < 0 ? cur + 0.5 : cur - 0.5;
        return Math.min(4, Math.max(1, next));
      });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  // Esc — закрыть
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Блокируем скролл фона, пока открыт просмотр
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  const zoomed = zoom > 1 && baseSize;

  const lightbox = (
    <div
      className="fixed inset-0 z-[30000] bg-black/90 backdrop-blur-sm flex items-center justify-center"
      onClick={onClose}
      data-testid={`${testIdPrefix}-lightbox`}
    >
      {/* Обёртка shrink-wrap: границы модалки = границы фото */}
      <div
        className="relative inline-block"
        onClick={(e) => e.stopPropagation()}
      >
        <div
          ref={frameRef}
          className="max-w-[92vw] max-h-[88vh] overflow-auto rounded-lg border border-white/15 shadow-2xl bg-black/40"
          data-testid={`${testIdPrefix}-lightbox-frame`}
        >
          <img
            ref={imgRef}
            src={src}
            alt=""
            onLoad={handleLoad}
            onClick={toggleZoom}
            onDoubleClick={toggleZoom}
            draggable={false}
            className={`block select-none rounded-lg transition-transform ${
              zoomed
                ? 'cursor-zoom-out'
                : 'max-w-[92vw] max-h-[88vh] min-w-[120px] cursor-zoom-in'
            }`}
            style={zoomed ? { width: `${baseSize.w * zoom}px`, maxWidth: 'none', maxHeight: 'none' } : undefined}
            data-testid={`${testIdPrefix}-lightbox-img`}
          />
        </div>
        {/* Кнопка закрытия — справа вверху, по границе фото */}
        <button
          type="button"
          onClick={onClose}
          className="absolute top-2 right-2 w-9 h-9 rounded-full bg-black/70 border border-white/25 flex items-center justify-center text-white/80 hover:text-white hover:bg-black/90 transition-colors"
          data-testid={`${testIdPrefix}-lightbox-close`}
          aria-label="Закрыть"
        >
          <X className="w-5 h-5" />
        </button>
      </div>
    </div>
  );

  return createPortal(lightbox, document.body);
}

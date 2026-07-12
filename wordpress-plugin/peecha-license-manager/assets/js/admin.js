(function ($) {
    function cfg(key, fallback) {
        if (window.peechaLmAdmin && peechaLmAdmin[key] !== undefined) {
            return peechaLmAdmin[key];
        }
        return fallback;
    }

    function toPersianDigits(value) {
        return String(value || '').replace(/\d/g, function (d) {
            return '۰۱۲۳۴۵۶۷۸۹'[d];
        });
    }

    function fromPersianDigits(value) {
        return String(value || '').replace(/[۰-۹]/g, function (d) {
            return '۰۱۲۳۴۵۶۷۸۹'.indexOf(d);
        });
    }

    function filterDateChars(value) {
        return fromPersianDigits(value).replace(/[^\d/\-]/g, '');
    }

    function formatJalaliFromGregorian(ymd) {
        if (!ymd || !window.persianDate) {
            return ymd || '';
        }
        var parts = String(ymd).split('-');
        if (parts.length !== 3) {
            return ymd;
        }
        var d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10), 12, 0, 0);
        if (isNaN(d.getTime())) {
            return ymd;
        }
        return toPersianDigits(new persianDate(d).format('YYYY/MM/DD'));
    }

    function formatJalaliUnix(unix) {
        if (!unix || !window.persianDate) {
            return '';
        }
        return toPersianDigits(new persianDate(unix).format('YYYY/MM/DD'));
    }

    function setGregorianHidden($hidden, unix) {
        if (!$hidden.length || !window.persianDate || !unix) {
            return;
        }
        try {
            var g = new persianDate(unix).toCalendar('gregorian').format('YYYY-MM-DD');
            $hidden.val(g);
        } catch (e) {
            /* keep previous value */
        }
    }

    function parseJalaliParts(text) {
        var raw = fromPersianDigits(text).trim();
        if (!raw) {
            return null;
        }
        var m = raw.match(/^(\d{4})[\/\-](\d{1,2})[\/\-](\d{1,2})$/);
        if (!m) {
            return null;
        }
        var y = parseInt(m[1], 10);
        var mo = parseInt(m[2], 10);
        var d = parseInt(m[3], 10);
        if (y < 1300 || y > 1500 || mo < 1 || mo > 12 || d < 1 || d > 31) {
            return null;
        }
        return { y: y, m: mo, d: d };
    }

    function formatJalaliParts(parts) {
        if (!parts) {
            return '';
        }
        var y = String(parts.y);
        var m = parts.m < 10 ? '0' + parts.m : String(parts.m);
        var d = parts.d < 10 ? '0' + parts.d : String(parts.d);
        return toPersianDigits(y + '/' + m + '/' + d);
    }

    function jalaliPartsToGregorian(parts) {
        if (!parts || !window.persianDate) {
            return '';
        }
        try {
            var pd = new persianDate([parts.y, parts.m, parts.d]);
            return pd.toCalendar('gregorian').format('YYYY-MM-DD');
        } catch (e) {
            return '';
        }
    }

    function showDateError($wrap, message) {
        var $err = $wrap.find('.peecha-jalali-error');
        var $display = $wrap.find('.peecha-jalali-display');
        if (message) {
            $err.text(message).show();
            $display.addClass('peecha-jalali-invalid').attr('aria-invalid', 'true');
            $wrap.addClass('peecha-jalali-wrap--invalid');
            if (!$display.attr('aria-describedby')) {
                $display.attr('aria-describedby', $err.attr('id') || '');
            }
            return false;
        }
        $err.hide().text('');
        $display.removeClass('peecha-jalali-invalid').attr('aria-invalid', 'false');
        $wrap.removeClass('peecha-jalali-wrap--invalid');
        return true;
    }

    function partsToServerValue(parts) {
        if (!parts) {
            return '';
        }
        var m = parts.m < 10 ? '0' + parts.m : String(parts.m);
        var d = parts.d < 10 ? '0' + parts.d : String(parts.d);
        return parts.y + '-' + m + '-' + d;
    }

    function syncManualInput($wrap) {
        var $hidden = $wrap.find('.peecha-jalali-value');
        var $display = $wrap.find('.peecha-jalali-display');
        var text = $display.val();
        var required = $wrap.data('required') === 1 || $wrap.data('required') === '1';

        if (!text || !String(text).trim()) {
            $hidden.val('');
            if (required) {
                return showDateError($wrap, cfg('dateRequired', 'تاریخ انقضا الزامی است.'));
            }
            return showDateError($wrap, '');
        }

        var parts = parseJalaliParts(text);
        if (!parts) {
            $hidden.val('');
            return showDateError($wrap, cfg('dateInvalid', 'تاریخ نامعتبر است. فرمت YYYY/MM/DD شمسی، مثلا 1404/03/25.'));
        }

        var gregorian = jalaliPartsToGregorian(parts);
        $hidden.val(gregorian || partsToServerValue(parts));
        $display.val(formatJalaliParts(parts));
        return showDateError($wrap, '');
    }

    function markMissing($wrap) {
        var msg = cfg('datepickerMissing', 'Datepicker not loaded');
        $wrap.find('.peecha-jalali-open').prop('disabled', true).attr('title', msg);
    }

    function openDatepicker($display) {
        try {
            if ($display.data('datepicker') && typeof $display.data('datepicker').show === 'function') {
                $display.data('datepicker').show();
                return;
            }
        } catch (e) {
            /* fall through */
        }
        $display.trigger('focus').trigger('click');
    }

    function ensureDatepicker($wrap, $hidden, $display) {
        if ($display.data('peechaJalaliReady') || !$.fn.persianDatepicker) {
            return;
        }

        $display.persianDatepicker({
            inline: false,
            format: 'YYYY/MM/DD',
            calendarType: 'persian',
            initialValue: false,
            autoClose: true,
            observer: true,
            calendar: {
                persian: { locale: 'fa' }
            },
            toolbox: {
                calendarSwitch: { enabled: false }
            },
            onSelect: function (unix) {
                setGregorianHidden($hidden, unix);
                $display.val(formatJalaliUnix(unix));
                showDateError($wrap, '');
            }
        });

        $display.data('peechaJalaliReady', true);
    }

    function initJalaliPickers() {
        $('.peecha-jalali-wrap').each(function () {
            var $wrap = $(this);
            var $hidden = $wrap.find('.peecha-jalali-value');
            var $display = $wrap.find('.peecha-jalali-display');
            var usePicker = String($wrap.data('jalaliPicker')) === '1';

            if (!$display.length || !$hidden.length) {
                return;
            }

            if ($wrap.data('peechaJalaliBound')) {
                return;
            }

            if ($wrap.hasClass('peecha-jalali-wrap--invalid')) {
                var $firstBad = $('.peecha-jalali-wrap--invalid').first();
                if ($firstBad.is($wrap)) {
                    $display.trigger('focus');
                }
            }

            if ($hidden.val()) {
                var shown = formatJalaliFromGregorian($hidden.val());
                if (!shown || /^\d{4}-\d{2}-\d{2}$/.test(String($hidden.val()))) {
                    if (!shown) {
                        shown = toPersianDigits(String($hidden.val()).replace(/-/g, '/'));
                    }
                }
                $display.val(shown);
            }

            $display.attr('placeholder', cfg('datePlaceholder', '1404/03/25'));

            $display.on('input', function () {
                var filtered = filterDateChars($display.val());
                if (filtered !== $display.val()) {
                    $display.val(filtered);
                }
                syncManualInput($wrap);
            });

            $display.on('blur', function () {
                syncManualInput($wrap);
            });

            if (usePicker) {
                if (!$.fn.persianDatepicker) {
                    markMissing($wrap);
                } else {
                    $display.on('focus', function () {
                        ensureDatepicker($wrap, $hidden, $display);
                    });
                    $wrap.find('.peecha-jalali-open').on('click', function (e) {
                        e.preventDefault();
                        ensureDatepicker($wrap, $hidden, $display);
                        openDatepicker($display);
                    });
                }
            }

            $wrap.data('peechaJalaliBound', true);
        });

        $('.peecha-lm-wrap form').on('submit', function (e) {
            var ok = true;
            $(this).find('.peecha-jalali-wrap').each(function () {
                if (!syncManualInput($(this))) {
                    ok = false;
                }
            });
            if (!ok) {
                e.preventDefault();
            }
        });
    }

    function initGregorianDates() {
        $('.peecha-gdate').each(function () {
            var $cell = $(this);
            var raw = $cell.data('gdate');
            if (!raw) {
                return;
            }
            $cell.text(formatJalaliFromGregorian(raw));
        });
    }

    function copyTextToClipboard(text) {
        if (!text) {
            return Promise.reject(new Error('empty'));
        }
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise(function (resolve, reject) {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            try {
                var ok = document.execCommand('copy');
                document.body.removeChild(ta);
                if (ok) {
                    resolve();
                } else {
                    reject(new Error('execCommand failed'));
                }
            } catch (err) {
                document.body.removeChild(ta);
                reject(err);
            }
        });
    }

    function initCopyApiKey() {
        var $btn = $('#peecha-copy-api-key');
        var input = document.getElementById('api_key');
        if (!$btn.length || !input) {
            return;
        }
        var defaultLabel = $btn.data('default-label') || cfg('copyLabel', 'Copy');
        var copiedLabel = $btn.data('copied-label') || cfg('copiedLabel', 'Copied');
        $btn.off('click.peechaCopy').on('click.peechaCopy', function (e) {
            e.preventDefault();
            var text = input.value || '';
            copyTextToClipboard(text).then(function () {
                $btn.text(copiedLabel);
                setTimeout(function () {
                    $btn.text(defaultLabel);
                }, 1500);
            }).catch(function () {
                input.focus();
                input.select();
                if (input.setSelectionRange) {
                    input.setSelectionRange(0, text.length);
                }
                window.alert(cfg('copyFailed', 'کپی نشد — متن را دستی انتخاب کنید (Ctrl+C)'));
            });
        });
    }

    function boot() {
        initJalaliPickers();
        initGregorianDates();
        initCopyApiKey();
    }

    $(boot);
    $(window).on('load', boot);
}(jQuery));

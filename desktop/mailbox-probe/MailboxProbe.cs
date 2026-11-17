using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace PrimeFlow.MailboxProbe
{
    public sealed class ProbeFailure : Exception
    {
        public ProbeFailure(string message) : base(message) { }
    }

    public sealed class MailPreview
    {
        public string Subject, Sender, Categories, Preview;
        public DateTime Received;
        public bool Unread;
    }

    public sealed class ProbeResult
    {
        public bool CategoriesRead, InboxRead, Offline;
        public string StoreName, IdentityMethod, ConnectionMode;
        public string Failure, Stage;
        public int? ErrorCode;
        public DateTime CheckedAt;
        public readonly List<string> Categories = new List<string>();
        public readonly List<MailPreview> Messages = new List<MailPreview>();
        public bool Success { get { return CategoriesRead && InboxRead; } }

        // Intentionally excludes message contents, senders, subjects, IDs and category names.
        public string Diagnostic()
        {
            return "PrimeFlow Outlook Read Test v1.1 (50 emails)\r\n" +
                "Mailbox: " + Reader.Target + "\r\n" +
                "Time (local): " + CheckedAt.ToString("yyyy-MM-dd HH:mm:ss zzz") + "\r\n" +
                "Result: " + (Success ? "LOCAL_READ_OK" : "LOCAL_READ_FAILED") + "\r\n" +
                "Identity: " + (IdentityMethod ?? "not_verified") + "\r\n" +
                "Outlook mode: " + (ConnectionMode ?? "unknown") + "\r\n" +
                "Categories read: " + CategoriesRead + "; count: " + Categories.Count + "\r\n" +
                "Inbox read: " + InboxRead + "; messages: " + Messages.Count + "\r\n" +
                "Stage: " + (Stage ?? "attach") + "\r\n" +
                "Error code: " + (ErrorCode.HasValue ? "0x" + unchecked((uint)ErrorCode.Value).ToString("X8") : "none") + "\r\n" +
                "Graph: NOT_TESTED\r\nMailbox type: NOT_DETERMINED\r\n" +
                "PrimeFlow upload: NONE\r\nMailbox writes: NONE\r\n";
        }
    }

    public static class Reader
    {
        public const string Target = "info@primexeu.com";
        public const int MessageLimit = 50;
        private const string OwnerEntryId = "http://schemas.microsoft.com/mapi/proptag/0x661B0102";

        private static bool IsTarget(string value)
        {
            return String.Equals((value ?? "").Trim(), Target, StringComparison.OrdinalIgnoreCase);
        }

        private static void Release(object value)
        {
            if (value != null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value);
        }

        public static ProbeResult ReadActiveOutlook(bool includePreview)
        {
            ProbeResult result = new ProbeResult { CheckedAt = DateTime.Now, Stage = "attach" };
            object application = null, session = null;
            try
            {
                // Attach only. No CreateObject, profile login, password or credential access.
                application = Marshal.GetActiveObject("Outlook.Application");
                session = ((dynamic)application).Session;
                ReadSession(session, includePreview, result);
            }
            catch (Exception error) { RecordFailure(result, error); }
            finally { Release(session); Release(application); }
            return result;
        }

        public static void RecordFailure(ProbeResult result, Exception error)
        {
            result.ErrorCode = error.HResult;
            ProbeFailure known = error as ProbeFailure;
            if (known != null) { result.Failure = known.Message; return; }
            result.Failure = result.Stage == "attach"
                ? "Nuk u gjet sesioni i Outlook klasik. Hape Outlook (classic), prit të shfaqet Inbox-i dhe provo sërish. Hapi të dy programet normalisht, jo si administrator."
                : "Outlook nuk e lejoi ose nuk e përfundoi leximin në hapin: " + result.Stage + ". Nëse kërkon identifikim apo shfaq bllokim sigurie, ndalo provën dhe na trego vetëm mesazhin/kodin.";
            // Do not display raw exception text, which may contain mailbox data or paths.
        }

        public static void ReadSession(dynamic session, bool includePreview, ProbeResult result)
        {
            object store = null, categories = null, inbox = null, items = null;
            try
            {
                result.Stage = "identify_mailbox";
                store = FindTargetStore(session, result);
                result.StoreName = Convert.ToString(((dynamic)store).DisplayName);
                int storeType = Convert.ToInt32(((dynamic)store).ExchangeStoreType);
                if (storeType != 0 && storeType != 1 && storeType != 4)
                    throw new ProbeFailure("Mailbox-i i zgjedhur nuk u identifikua si Exchange mailbox. Prova u ndal pa lexuar mesazhe.");
                // Connection state describes Outlook, not a new Graph or live-mailbox test.
                try
                {
                    result.Offline = Convert.ToBoolean(session.Offline);
                    result.ConnectionMode = result.Offline ? "offline / cached" : "Outlook reports online";
                    try { result.ConnectionMode += " (ExchangeConnectionMode=" + Convert.ToInt32(session.ExchangeConnectionMode) + ")"; }
                    catch { }
                }
                catch { result.ConnectionMode = "unknown; local cache may be used"; }

                result.Stage = "categories";
                categories = ((dynamic)store).Categories;
                int count = Convert.ToInt32(((dynamic)categories).Count);
                for (int index = 1; index <= count; index++)
                {
                    object category = null;
                    try
                    {
                        category = ((dynamic)categories).Item(index);
                        result.Categories.Add(Convert.ToString(((dynamic)category).Name));
                    }
                    finally { Release(category); }
                }
                result.CategoriesRead = true; // Empty collection is a valid result.

                result.Stage = "inbox";
                // Store-specific Inbox; never session.GetDefaultFolder (could be another mailbox).
                inbox = ((dynamic)store).GetDefaultFolder(6);
                items = ((dynamic)inbox).Items;
                ReadMessages(items, includePreview, result);
                result.InboxRead = true;
                result.Stage = "complete";
            }
            finally { Release(items); Release(inbox); Release(categories); Release(store); }
        }

        private static object FindTargetStore(dynamic session, ProbeResult result)
        {
            object accounts = null;
            var matches = new List<object>();
            try
            {
                accounts = session.Accounts;
                int count = Convert.ToInt32(((dynamic)accounts).Count);
                for (int i = 1; i <= count; i++)
                {
                    object account = null;
                    try
                    {
                        account = ((dynamic)accounts).Item(i);
                        if (IsTarget(Convert.ToString(((dynamic)account).SmtpAddress)) && Convert.ToInt32(((dynamic)account).AccountType) == 0)
                            matches.Add(((dynamic)account).DeliveryStore);
                    }
                    finally { Release(account); }
                }
            }
            finally { Release(accounts); }
            if (matches.Count == 1) { result.IdentityMethod = "exact_account_smtp"; return matches[0]; }
            if (matches.Count > 1)
            {
                foreach (object match in matches) Release(match);
                throw new ProbeFailure("U gjetën disa lidhje për info@primexeu.com. Nuk u zgjodh asnjë mailbox automatikisht.");
            }

            // Covers an additional Exchange store only if its owner SMTP can be verified.
            // DisplayName alone is not an identity check and is never accepted.
            object stores = null;
            try
            {
                stores = session.Stores;
                int count = Convert.ToInt32(((dynamic)stores).Count);
                for (int i = 1; i <= count; i++)
                {
                    object store = null, accessor = null, entry = null, owner = null;
                    bool selected = false;
                    try
                    {
                        store = ((dynamic)stores).Item(i);
                        accessor = ((dynamic)store).PropertyAccessor;
                        object binary = ((dynamic)accessor).GetProperty(OwnerEntryId);
                        string id = ((dynamic)accessor).BinaryToString(binary);
                        entry = session.GetAddressEntryFromID(id);
                        owner = ((dynamic)entry).GetExchangeUser();
                        if (owner != null && IsTarget(Convert.ToString(((dynamic)owner).PrimarySmtpAddress)))
                        {
                            matches.Add(store);
                            selected = true;
                        }
                    }
                    catch { /* An unverified/PST/other store is never read. */ }
                    finally { Release(owner); Release(entry); Release(accessor); if (!selected) Release(store); }
                }
            }
            finally { Release(stores); }
            if (matches.Count == 1) { result.IdentityMethod = "exact_exchange_owner_smtp"; return matches[0]; }
            foreach (object match in matches) Release(match);
            throw new ProbeFailure(matches.Count == 0
                ? "Nuk u verifikua mailbox-i info@primexeu.com në këtë profil Outlook. Asnjë Inbox tjetër nuk u lexua. Provoje në laptopin dhe profilin ku menaxherja e përdor këtë adresë."
                : "U gjetën disa Exchange stores për këtë adresë. Prova u ndal pa zgjedhur njërin.");
        }

        public static void ReadMessages(dynamic items, bool includePreview, ProbeResult result)
        {
            items.Sort("[ReceivedTime]", true); // Collection order only, not Outlook view or messages.
            int count = Convert.ToInt32(items.Count);
            int scanned = 0;
            for (int i = 1; i <= count && result.Messages.Count < MessageLimit; i++)
            {
                if (++scanned > 1000)
                    throw new ProbeFailure("Inbox-i përmban shumë artikuj jo-email. Prova u ndal para se të verifikonte 50 email-et e fundit.");
                object item = null;
                try
                {
                    item = items.Item(i);
                    if (Convert.ToInt32(((dynamic)item).Class) != 43) continue;
                    MailPreview message = new MailPreview();
                    message.Subject = Convert.ToString(((dynamic)item).Subject);
                    message.Sender = Convert.ToString(((dynamic)item).SenderName);
                    message.Received = Convert.ToDateTime(((dynamic)item).ReceivedTime);
                    message.Categories = Convert.ToString(((dynamic)item).Categories);
                    message.Unread = Convert.ToBoolean(((dynamic)item).UnRead);
                    // Read plain text only on explicit opt-in; no HTML rendering or attachments.
                    message.Preview = includePreview ? ShortPreview(Convert.ToString(((dynamic)item).Body)) : "(Fragmenti i tekstit nuk u kërkua.)";
                    result.Messages.Add(message);
                }
                finally { Release(item); }
            }
        }

        public static string ShortPreview(string text)
        {
            text = (text ?? "").Replace('\0', ' ').Replace("\r\n", "\n");
            return text.Length <= 400 ? text : text.Substring(0, 400) + "…";
        }
    }

    public sealed class ProbeForm : Form
    {
        private readonly Button read = new Button { Text = "Provo leximin", AutoSize = true };
        private readonly Button copy = new Button { Text = "Kopjo diagnostikën pa përmbajtje", AutoSize = true, Enabled = false };
        private readonly CheckBox preview = new CheckBox { Text = "Lexo edhe fragmentin e tekstit (deri 400 karaktere/email)", AutoSize = true };
        private readonly Label status = new Label { Text = "Prova ende nuk ka filluar.", Dock = DockStyle.Fill, ForeColor = Color.FromArgb(31, 60, 95) };
        private readonly TextBox categories = new TextBox { Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical };
        private readonly DataGridView messages = new DataGridView { Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false, AllowUserToDeleteRows = false, AutoGenerateColumns = false, AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill, SelectionMode = DataGridViewSelectionMode.FullRowSelect, MultiSelect = false, RowHeadersVisible = false, BackgroundColor = Color.White, AutoSizeRowsMode = DataGridViewAutoSizeRowsMode.AllCells };
        private readonly TextBox body = new TextBox { Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Vertical };
        private readonly List<MailPreview> displayed = new List<MailPreview>();
        private ProbeResult last;
        private bool running;

        public ProbeForm()
        {
            Text = "PrimeFlow · Provë lokale Outlook v1.1 · 50 email-e · Vetëm lexim";
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(1100, 820); MinimumSize = new Size(760, 640);
            Font = new Font("Segoe UI", 10);
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(20), ColumnCount = 1, RowCount = 10 };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 68));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 45));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 68));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 26));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 85));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 100));
            layout.Controls.Add(new Label { Text = "info@primexeu.com · Provë lokale Outlook", AutoSize = true, Font = new Font("Segoe UI", 16, FontStyle.Bold) }, 0, 0);
            layout.Controls.Add(new Label { Dock = DockStyle.Fill, Text = "Hape Outlook (classic) dhe prit të shfaqet Inbox-i. Lexohen kategoritë dhe deri në 50 email-et më të fundit. Asgjë nuk dërgohet në PrimeFlow; nuk ruhen skedarë dhe nuk ndryshohen email-et. Nuk kërkohet fjalëkalim nga ky program." }, 0, 1);
            layout.Controls.Add(preview, 0, 2);
            var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = true };
            buttons.Controls.Add(read); buttons.Controls.Add(copy);
            layout.Controls.Add(buttons, 0, 3);
            layout.Controls.Add(status, 0, 4);
            layout.Controls.Add(new Label { Text = "Kategoritë e mailbox-it", AutoSize = true }, 0, 5);
            layout.Controls.Add(categories, 0, 6);
            layout.Controls.Add(new Label { Text = "Email-et më të fundit në Inbox · sipas datës së pranimit", AutoSize = true }, 0, 7);
            foreach (var column in new[] { "Data", "Dërguesi", "Subjekti", "Kategoritë", "Leximi" })
                messages.Columns.Add(new DataGridViewTextBoxColumn { HeaderText = column, SortMode = DataGridViewColumnSortMode.NotSortable });
            messages.Columns[2].FillWeight = 180;
            layout.Controls.Add(messages, 0, 8);
            layout.Controls.Add(body, 0, 9);
            Controls.Add(layout);
            read.Click += delegate { StartRead(); };
            copy.Click += delegate { if (last != null) { try { Clipboard.SetText(last.Diagnostic()); } catch { MessageBox.Show("Nuk u kopjua diagnostika. Provo përsëri."); } } };
            messages.SelectionChanged += delegate
            {
                int index = messages.CurrentRow == null ? -1 : messages.CurrentRow.Index;
                body.Text = index >= 0 && index < displayed.Count ? displayed[index].Preview : "";
            };
            FormClosing += delegate(object sender, FormClosingEventArgs e)
            {
                if (running) e.Cancel = true; // Do not abandon a COM request while Outlook may show a prompt.
            };
        }

        private void StartRead()
        {
            if (running) return;
            running = true; read.Enabled = false; copy.Enabled = false; preview.Enabled = false;
            last = null; displayed.Clear(); messages.Rows.Clear(); categories.Clear(); body.Clear();
            status.ForeColor = Color.FromArgb(31, 60, 95);
            status.Text = "Duke lexuar profilin ekzistues… Nëse Outlook kërkon hyrje ose shfaq bllokim, ndalo aty.\r\nMos ndrysho cilësimet e sigurisë. Mos dërgo fjalëkalime ose kode.";
            bool include = preview.Checked;
            var worker = new Thread(delegate()
            {
                ProbeResult result = Reader.ReadActiveOutlook(include);
                BeginInvoke((Action)delegate { ShowResult(result); });
            });
            worker.SetApartmentState(ApartmentState.STA);
            worker.IsBackground = true;
            worker.Start();
        }

        public void ShowResult(ProbeResult result)
        {
            last = result; running = false; read.Enabled = true; copy.Enabled = true; preview.Enabled = true;
            displayed.Clear(); displayed.AddRange(result.Messages);
            categories.Text = result.CategoriesRead ? (result.Categories.Count == 0 ? "Nuk u kthyen kategori të përcaktuara." : String.Join("   |   ", result.Categories)) : "Leximi i kategorive nuk u verifikua.";
            messages.Rows.Clear();
            foreach (MailPreview message in displayed)
                messages.Rows.Add(message.Received.ToString("dd.MM.yyyy HH:mm"), message.Sender, message.Subject, message.Categories, message.Unread ? "Pa lexuar" : "Lexuar");
            status.ForeColor = result.Success ? Color.DarkGreen : Color.Maroon;
            status.Text = result.Success
                ? "LEXIMI LOKAL KALOI · " + result.Categories.Count + " kategori · " + result.Messages.Count + " email-e\r\n" + result.ConnectionMode + " · Mund të përdoret kopja lokale. Graph dhe lloji User/Shared nuk u verifikuan."
                : "PROVA NUK U PËRFUNDUA · " + result.Failure;
            if (messages.Rows.Count > 0)
            {
                messages.CurrentCell = messages.Rows[0].Cells[0];
                body.Text = displayed[0].Preview;
            }
        }
    }

    public static class Program
    {
        [STAThread]
        public static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new ProbeForm());
        }
    }
}
